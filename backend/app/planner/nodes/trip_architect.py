"""
TripArchitect Node - LLM (Smart) core planning node.

This is "The Boss" - the General Agent in the UI.
Responsibilities:
- Manages the TripPlan (SSoT)
- Calls fetch_travel_tiles tool when needed
- Handles Pre-Core Mode (S0) - inspiration conversations
- Asks for missing required fields
- Respects constraints from Vertical Specialist

Key Principle: "The Architect sees the whole picture."

V2 Enhancement: Uses LLM for ALL field extraction (no regex).
GPT-4o-mini resolves relative dates, budget, travelers with current date injection.
"""

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List

from app.config import settings
from app.planner.llm_factory import get_llm_by_model
from app.planner.patterns_registry import SETTINGS_KEYWORDS
from app.planner.state import (
    ExtractedSettingsFields,
    ExtractedTripFields,
    GraphState,
    TripPlan,
    create_missing_fields_response,
    get_missing_fields,
    trip_plan_is_ready,
)
from app.tools.tile_service import fetch_travel_tiles

logger = logging.getLogger(__name__)


async def _extract_fields_with_llm(
    user_text: str,
    current_plan: TripPlan,
) -> tuple[ExtractedTripFields, dict]:
    """
    Use LLM to extract trip fields from user text.

    Injects current date for relative date resolution.
    Uses gpt-4o-mini for speed (~200-400ms).

    This replaces all regex-based extraction with pure LLM parsing.
    Returns tuple of (ExtractedTripFields, token_usage_dict).
    """
    llm = get_llm_by_model(settings.extraction_model, temperature=0)
    structured_llm = llm.with_structured_output(
        ExtractedTripFields, include_raw=True, method="function_calling"
    )

    # Inject current date for relative date resolution
    today = datetime.now()
    today_str = today.strftime("%A, %B %d, %Y")  # "Sunday, January 26, 2026"

    prompt = f"""Extract trip planning fields from the user message.

CURRENT DATE: {today_str}

FIELD DEFINITIONS:
- destination: WHERE they're traveling TO (the vacation place)
- origin: WHERE they're departing FROM (their home city, e.g. "from New York", "flying from London")
  IMPORTANT: Origin is ONLY set if user explicitly mentions where they're FLYING FROM.
  "I want to go to Bali" does NOT set origin - only destination.

EXISTING PLAN (for context - don't overwrite unless user explicitly changes):
- Destination: {current_plan.destination or "Not set"}
- Origin: {current_plan.origin or "Not set"}
- Dates: {current_plan.start_date or "Not set"} to {current_plan.end_date or "Not set"}
- Travelers: {current_plan.adults} adults, {current_plan.children} children
- Budget: {current_plan.budget or "Not set"}

RULES:
1. Convert ALL relative dates to YYYY-MM-DD format based on CURRENT DATE:
   - "tomorrow" → calculate {(today + timedelta(days=1)).strftime("%Y-%m-%d")}
   - "next week" → Monday of next week
   - "next Friday" → actual Friday date
   - "in March" → 2026-03-01 (or 2027 if March has passed)
   - "for 5 days" → set duration_days=5 (don't set end_date)

2. Extract budget as numeric USD:
   - "2k" → 2000
   - "under $3000" → 3000
   - "$1500 per person" → 1500
   - "luxury" → budget_tier="luxury" (not budget amount)

3. Only extract fields EXPLICITLY mentioned in this message.
   Return null for fields not mentioned.
   CRITICAL: Origin should be null unless user says "from <city>" or "flying from <city>".

4. Don't change existing values unless user explicitly updates them.
   Exception: If user says "actually Paris" and destination was "London", update it.

USER MESSAGE: {user_text}
"""

    try:
        result = await structured_llm.ainvoke(prompt)
        # Extract parsed result and token usage
        parsed = result["parsed"]
        if parsed is None:
            raise ValueError("Structured output returned parsed=None")
        raw = result["raw"]
        from app.planner.llm_factory import extract_token_usage

        token_usage = extract_token_usage(raw, model=settings.extraction_model)
        logger.debug(f"LLM extracted fields: {parsed}")
        return parsed, token_usage
    except Exception as e:
        logger.warning(f"LLM extraction failed: {e}")
        return ExtractedTripFields(), {}


# =============================================================================
# Settings Extraction (Booking Toggles, Flight/Hotel Preferences)
# =============================================================================

SETTINGS_EXTRACTION_PROMPT = """Extract booking settings from the user message.

RULES:
1. BOOKING TOGGLES (output MUST be: "off", "suggested", or "on"):
   - "No flights" / "Turn off flights" / "I don't need flights" → flights_toggle: "off"
   - "Include flights" / "I want flights" / "Turn on flights" → flights_toggle: "on"
   - Same pattern for hotels_toggle, activities_toggle
   - CRITICAL: A toggle is "off" ONLY when the user EXPLICITLY asks to remove/disable it.
     Mentioning activities does NOT mean hotels should be off.
     Mentioning flights does NOT mean activities should be off.
     If the user does not mention a category AT ALL, leave its toggle null.
   - WRONG: "yoga and cooking in Bali" → hotels_toggle: "off" (user never said no hotels!)
   - WRONG: "I want to go diving" → flights_toggle: "off" (user never said no flights!)
   - RIGHT: "no hotels, just activities" → hotels_toggle: "off", activities_toggle: "on"
   - RIGHT: "skip flights" → flights_toggle: "off"

2. FLIGHT SETTINGS:
   - "Direct flights only" / "No layovers" → flight_direct_only: true
   - flight_cabin_class MUST be one of: "economy", "premium_economy", "business", "first"
     - "Business class flights" → "business"
     - "First class" → "first"
     - "Economy" / "Coach" → "economy"
   - "One way" / "Not round trip" → flight_round_trip: false

3. HOTEL SETTINGS (hotel_min_stars: 0-5):
   - "5 star hotel" / "Luxury resort" → hotel_min_stars: 5
   - "4 star or better" / "Upscale hotel" → hotel_min_stars: 4
   - "3 star" / "Mid-range hotel" → hotel_min_stars: 3
   - "Budget hotel" / "Cheap stay" → hotel_min_stars: 0
   - Ambiguous terms like "nice" or "good" → DO NOT set (leave null)

4. Only extract fields EXPLICITLY mentioned. Return null for anything ambiguous.
   When in doubt, return null. Never infer a toggle from context — only from direct statements.

USER MESSAGE: {user_text}
"""


async def _extract_settings_with_llm(user_text: str) -> tuple[ExtractedSettingsFields, dict]:
    """
    Use LLM to extract booking settings from user text.

    Only called when settings-related keywords are detected.
    Returns tuple of (ExtractedSettingsFields, token_usage_dict).
    """
    llm = get_llm_by_model(settings.extraction_model, temperature=0)
    structured_llm = llm.with_structured_output(
        ExtractedSettingsFields, include_raw=True, method="function_calling"
    )

    prompt = SETTINGS_EXTRACTION_PROMPT.format(user_text=user_text)

    try:
        result = await structured_llm.ainvoke(prompt)
        parsed = result["parsed"]
        if parsed is None:
            raise ValueError("Structured output returned parsed=None")
        raw = result["raw"]
        from app.planner.llm_factory import extract_token_usage

        token_usage = extract_token_usage(raw, model=settings.extraction_model)
        logger.debug(f"LLM extracted settings: {parsed}")
        return parsed, token_usage
    except Exception as e:
        logger.warning(f"Settings LLM extraction failed: {e}")
        return ExtractedSettingsFields(), {}


def _has_settings_keywords(text: str) -> bool:
    """Check if user text contains settings-related keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in SETTINGS_KEYWORDS)


# =============================================================================
# Flexible Date Resolution
# =============================================================================

FLEXIBLE_DATE_KEYWORDS = ["flexible", "whenever", "anytime", "not sure when", "don't know when"]


def _resolve_flexible_dates(plan: TripPlan, user_text: str, metadata: dict) -> TripPlan:
    """
    Auto-resolve 'flexible' dates to concrete dates.

    The engine cannot run on 'flexible' - we need concrete dates for API queries.
    Defaults to: Start Date = Today + 30 days, Duration = 7 days
    """
    from app.debug_utils import _debug_log

    text_lower = user_text.lower()
    if not any(kw in text_lower for kw in FLEXIBLE_DATE_KEYWORDS):
        return plan

    # Only resolve if dates aren't already set
    if plan.start_date:
        return plan

    now = datetime.now()
    default_start = (now + timedelta(days=30)).strftime("%Y-%m-%d")
    default_end = (now + timedelta(days=37)).strftime("%Y-%m-%d")

    # Validate start is in the future (guard against server time skew)
    if datetime.fromisoformat(default_start) > now:
        plan.start_date = default_start
        plan.end_date = default_end
        _debug_log(f"Auto-resolved flexible dates: {default_start} to {default_end}")

        # Flag for synthesizer to explain the default
        metadata["flexible_date_resolved"] = True
        metadata["resolved_start_date"] = default_start
        metadata["resolved_end_date"] = default_end

    return plan


def _auto_toggle_flights(
    plan: TripPlan,
    prev_origin: str | None,
    extracted_settings: dict,
    metadata: dict,
) -> None:
    """
    Auto-toggle flights based on origin presence.

    Implements the behavior documented in schemas.py:
    "Upgrades to 'suggested' when origin is set"

    Precedence Rules:
    1. Explicit user preference wins (e.g., "No flights" keeps flights OFF)
    2. Origin added → auto-enable flights to "suggested"
    3. Origin removed → auto-disable flights to "off"

    NOTE: TripPlan (internal graph state) does NOT have booking_types.
    We set extracted_settings which gets merged into trip_inputs.booking_types
    during _v2_result_to_v1_format conversion (plan_graph_v2.py lines 866-877).
    """
    from app.debug_utils import _debug_log

    # 1. Respect explicit user preference in THIS turn
    if extracted_settings.get("flights_toggle") is not None:
        _debug_log(f"Flights: user explicit = {extracted_settings.get('flights_toggle')}")
        return

    current_origin = plan.origin

    # 2. Origin added → enable flights
    if current_origin and not prev_origin:
        # Update extracted_settings (merged into trip_inputs.booking_types during result conversion)
        metadata.setdefault("extracted_settings", {})
        metadata["extracted_settings"]["flights_toggle"] = "suggested"
        metadata["auto_toggle_flights"] = {"action": "enabled", "origin": current_origin}
        _debug_log(f"Flights auto-toggled to 'suggested' (origin: {current_origin})")

    # 3. Origin removed → disable flights
    elif not current_origin and prev_origin:
        # Update extracted_settings (merged into trip_inputs.booking_types during result conversion)
        metadata.setdefault("extracted_settings", {})
        metadata["extracted_settings"]["flights_toggle"] = "off"
        metadata["auto_toggle_flights"] = {"action": "disabled", "prev_origin": prev_origin}
        _debug_log("Flights auto-toggled to 'off' (origin cleared)")


async def _update_trip_plan_from_llm(
    plan: TripPlan,
    user_text: str,
) -> tuple[TripPlan, dict]:
    """
    Update trip plan using LLM-extracted fields.

    This replaces the old regex-based _update_trip_plan_from_text().
    Returns tuple of (updated_plan, token_usage_dict).
    """
    from app.debug_utils import _debug_log

    extracted, token_usage = await _extract_fields_with_llm(user_text, plan)

    # Print token usage for architect extraction
    if token_usage:
        from app.debug_utils import log_tokens

        log_tokens(
            "ARCHITECT",
            token_usage.get("prompt_tokens", 0),
            token_usage.get("completion_tokens", 0),
            token_usage.get("total_tokens", 0),
        )

    # Apply extracted fields (only non-null values)
    # Title-case place names for proper display (LLM may return lowercase)
    if extracted.destination:
        plan.destination = extracted.destination.title()
        _debug_log(f"LLM extracted destination: {extracted.destination}")

    if extracted.origin:
        plan.origin = extracted.origin.title()
        _debug_log(f"LLM extracted origin: {extracted.origin}")

    if extracted.start_date:
        plan.start_date = extracted.start_date
        _debug_log(f"LLM extracted start_date: {extracted.start_date}")

    if extracted.end_date:
        plan.end_date = extracted.end_date
        _debug_log(f"LLM extracted end_date: {extracted.end_date}")
    elif extracted.duration_days and extracted.start_date:
        # Calculate end date from duration
        try:
            start = datetime.fromisoformat(extracted.start_date)
            plan.end_date = (start + timedelta(days=extracted.duration_days)).strftime("%Y-%m-%d")
            _debug_log(
                f"LLM calculated end_date from duration: {plan.end_date} "
                f"({extracted.duration_days} days)"
            )
        except ValueError:
            pass

    if extracted.adults:
        plan.adults = extracted.adults
        plan.travelers = extracted.adults + (extracted.children or plan.children)
        _debug_log(f"LLM extracted adults: {extracted.adults}")

    if extracted.children is not None:
        plan.children = extracted.children
        plan.travelers = plan.adults + extracted.children
        _debug_log(f"LLM extracted children: {extracted.children}")

    if extracted.budget:
        plan.budget = extracted.budget
        _debug_log(f"LLM extracted budget: {extracted.budget}")

    if extracted.trip_type:
        plan.trip_type = extracted.trip_type
        _debug_log(f"LLM extracted trip_type: {extracted.trip_type}")

    return plan, token_usage


def _detect_and_handle_pivot(state: "GraphState", old_destination: str | None) -> bool:
    """
    Detects if destination changed and clears dependent state.
    Returns True if pivot occurred.

    Preserves: origin, dates, travelers, budget
    Clears: itinerary_blocks, constraints, segments, tiles, strategy metadata
    """
    new_destination = state.trip_plan.destination

    # No pivot if same destination or initial setup
    if not old_destination or not new_destination:
        return False
    if old_destination.lower() == new_destination.lower():
        return False

    # PIVOT DETECTED - Clear dependent state
    from app.debug_utils import log

    log("ARCHITECT", "PIVOT DETECTED", data=f"{old_destination} -> {new_destination}")

    state.trip_plan.itinerary_blocks = []
    state.trip_plan.constraints = []
    state.trip_plan.segments = []
    state.tiles = {}

    # Clear strategy metadata
    state.metadata["strategy_sections"] = []
    state.metadata["executed_strategy_topics"] = []
    state.metadata["pending_strategy_topics"] = []

    # Reset view state to discovery phase
    state.metadata["plan_view_state"] = "S2_STRATEGY_READY"

    # Signal to frontend
    state.metadata["pivot_detected"] = {"from": old_destination, "to": new_destination}

    return True


def _block_destination_switch_in_architect(
    state: "GraphState",
    old_destination: str | None,
) -> bool:
    """
    Enforce destination lock at architect level.

    Router may not extract destination changes for every pre-plan utterance.
    Architect extraction is the final gate to prevent silent destination pivots.
    """
    new_destination = state.trip_plan.destination
    if not old_destination or not new_destination:
        return False
    if old_destination.lower() == new_destination.lower():
        return False

    state.trip_plan.destination = old_destination
    state.last_summary = (
        "I can't switch destinations mid-plan. "
        f"You're currently planning **{old_destination}**. "
        f"To change to **{new_destination}**, click the **RESET** button first."
    )
    state.suggested_replies = [
        f"Continue with {old_destination}",
        "Why do I need to click RESET?",
        "Set my dates",
    ]
    state.metadata["short_circuit_response"] = True
    state.metadata["short_circuit_type"] = "destination_locked"
    state.metadata["destination_switch_blocked"] = {
        "from": old_destination,
        "to": new_destination,
    }
    state.metadata["exploration_mode"] = False
    return True


# =============================================================================
# Architect Prompt Templates (for reference - templates used in responses)
# =============================================================================

# These templates are used for generating responses in different modes.
# The actual field extraction is now handled by _extract_fields_with_llm().


# =============================================================================
# TripArchitect Class
# =============================================================================


class TripArchitect:
    """
    The Core planning node.

    Handles:
    - Pre-Core (S0): Inspiration mode
    - Planning: Building the trip with tools
    - Missing fields: Trigger Setup Modal
    """

    def __init__(self):
        self.debug = settings.debug_plan_messages

    def determine_mode(self, state: GraphState) -> str:
        """
        Determine the current operating mode.

        Returns: "pre_core", "missing_fields", or "planning"
        """
        plan = state.trip_plan

        # Check if we have the minimum to plan
        if not trip_plan_is_ready(plan):
            missing = get_missing_fields(plan)

            # If no destination at all, we're in inspiration mode
            if "destination" in missing:
                return "pre_core"

            # If we have destination but missing dates, ask for them
            return "missing_fields"

        return "planning"

    def generate_pre_core_response(self, state: GraphState, user_text: str) -> str:
        """
        Generate a Pre-Core (S0) inspiration response.

        This is conversational - no tool calls.
        Note: Destination extraction is now handled by LLM in _update_trip_plan_from_llm()
        before this method is called. If we're in pre_core mode, destination wasn't found.
        """
        # Check if LLM extraction found a destination (already in state from earlier step)
        potential_dest = state.trip_plan.destination

        if potential_dest:
            # Acknowledge the destination, ask about dates/interests
            return (
                f"Great choice! {potential_dest} sounds wonderful. "
                "When are you thinking of going? And what kind of experience "
                "are you looking for - adventure, relaxation, or a mix of both?"
            )

        # No destination yet - ask leading questions
        text_lower = user_text.lower()

        if any(w in text_lower for w in ["beach", "warm", "sun", "tropical"]):
            return (
                "I love a good beach escape! Are you thinking somewhere like "
                "Bali, the Maldives, or maybe the Caribbean? Each has its own vibe."
            )

        if any(w in text_lower for w in ["adventure", "active", "outdoor"]):
            return (
                "Adventure seeker! Are you drawn to mountains, water sports, "
                "or maybe exploring off-the-beaten-path destinations?"
            )

        if any(w in text_lower for w in ["relax", "chill", "peaceful", "quiet"]):
            return (
                "A relaxing getaway sounds perfect. Would you prefer a beach "
                "resort, a mountain retreat, or maybe a spa destination?"
            )

        # Default opener
        return (
            "I'd love to help you plan an amazing trip! What kind of experience "
            "are you dreaming of? Beach relaxation, mountain adventure, "
            "cultural exploration, or something else?"
        )

    def generate_missing_fields_response(self, state: GraphState) -> Dict[str, Any]:
        """
        Generate structured response for missing fields.

        Returns dict that triggers Setup Modal.
        """
        missing_response = create_missing_fields_response(state.trip_plan)

        if missing_response:
            return missing_response.model_dump()

        return {"type": "missing_fields", "fields": [], "message": "Ready to plan!"}

    def should_fetch_tiles(self, state: GraphState, intent: str) -> bool:
        """
        Determine if we should call fetch_travel_tiles.

        Fetch tiles ONLY when:
        - Plan is ready (destination + dates)
        - Intent is "booking" (user clicked Build Plan button)

        Do NOT auto-fetch tiles just because plan is ready.
        User must explicitly click "Build Plan" to trigger tile fetching.
        """
        plan = state.trip_plan
        is_ready = trip_plan_is_ready(plan)

        logger.debug(
            f"should_fetch_tiles: intent={intent}, plan_ready={is_ready}, "
            f"dest={plan.destination}, start_date={plan.start_date}, "
            f"existing_tiles={bool(state.tiles and any(state.tiles.values()))}"
        )

        if not is_ready:
            logger.debug("should_fetch_tiles: returning False (plan not ready)")
            return False

        # Skip if logistics already provided tiles (avoid 13s redundant fetch)
        has_hotels = bool(state.tiles.get("hotels"))
        has_activities = bool(state.tiles.get("activities"))
        if has_hotels or has_activities:
            logger.debug(
                f"should_fetch_tiles: returning False (logistics tiles exist: "
                f"hotels={has_hotels}, activities={has_activities})"
            )
            return False

        # ONLY fetch tiles for booking intent (triggered by "Build plan" button)
        # Do NOT auto-fetch - user must explicitly request plan generation
        if intent == "booking":
            logger.debug("should_fetch_tiles: returning True (booking intent)")
            return True

        logger.debug("should_fetch_tiles: returning False (waiting for Build Plan click)")
        return False

    async def fetch_tiles_for_plan(self, state: GraphState) -> Dict[str, List[Dict]]:
        """
        Fetch tiles for the current plan.

        Respects constraints from Specialist.
        Preserves flights from logistics_node if already set.
        """
        plan = state.trip_plan
        tiles_result = {}

        from app.debug_utils import _debug_info

        _debug_info(
            "FETCH_TILES",
            f"dest={plan.destination}, origin={plan.origin}, "
            f"dates={plan.start_date} to {plan.end_date}",
        )
        logger.info(
            f"fetch_tiles_for_plan: dest={plan.destination}, "
            f"origin={plan.origin}, dates={plan.start_date} to {plan.end_date}"
        )

        # Build constraints dict from Specialist
        constraints = {}
        for c in plan.constraints:
            constraints[c.rule] = True

        # Fetch each category
        for category in ["hotels", "flights", "activities"]:
            # PRESERVE flights from logistics_node if already set
            # (curated/sanitized flights with proper airline names and safety logic)
            if category == "flights" and state.tiles.get("flights"):
                _debug_info(
                    "FETCH_TILES",
                    f"PRESERVING {len(state.tiles['flights'])} flights from logistics_node",
                )
                tiles_result["flights"] = state.tiles["flights"]
                continue

            # PRESERVE activities from logistics_node if already set
            # (selective backfill tiles for pure Tier 1 trips — Phase 5.6 needs these)
            if category == "activities" and state.tiles.get("activities"):
                _debug_info(
                    "FETCH_TILES",
                    f"PRESERVING {len(state.tiles['activities'])} activities from logistics_node",
                )
                tiles_result["activities"] = state.tiles["activities"]
                continue

            # Check if we need origin for flights
            if category == "flights" and not plan.origin:
                _debug_info("FETCH_TILES", "SKIPPING flights - plan.origin is empty!")
                logger.debug(f"fetch_tiles_for_plan: skipping {category} (no origin)")
                continue

            _debug_info("FETCH_TILES", f"Fetching {category}...")
            logger.debug(f"fetch_tiles_for_plan: fetching {category}...")
            result = await fetch_travel_tiles.ainvoke(
                {
                    "category": category,
                    "location": plan.destination or "",
                    "start_date": plan.start_date,
                    "end_date": plan.end_date,
                    "origin": plan.origin,
                    "adults": plan.adults,
                    "children": plan.children,
                    "budget": plan.budget,
                    "constraints": constraints,
                }
            )

            if result.get("success"):
                tile_count = len(result.get("tiles", []))
                _debug_info("FETCH_TILES", f"{category} returned {tile_count} tiles")
                logger.info(f"fetch_tiles_for_plan: {category} returned {tile_count} tiles")
                tiles_result[category] = result.get("tiles", [])
            else:
                _debug_info("FETCH_TILES", f"{category} FAILED: {result.get('error', 'unknown')}")
                logger.warning(
                    f"fetch_tiles_for_plan: {category} failed - {result.get('error', 'unknown')}"
                )

        logger.info(
            "fetch_tiles_for_plan: total tiles = {k: len(v) for k, v in tiles_result.items()}"
        )
        return tiles_result

    def generate_planning_response(self, state: GraphState, _user_text: str) -> str:
        """
        Generate a planning mode response.

        May include tile fetching results.
        """
        plan = state.trip_plan

        # Simple response based on what we have
        response_parts = []

        # Build tile summary (one sentence for all categories)
        tile_parts = []
        for category in ("hotels", "flights", "activities"):
            tiles = state.tiles.get(category, [])
            if isinstance(tiles, list) and tiles:
                count = len(tiles)
                if count == 1:
                    if category.endswith("ies"):
                        label = category[:-3] + "y"
                    elif category.endswith("s"):
                        label = category[:-1]
                    else:
                        label = category
                else:
                    label = category
                tile_parts.append(f"**{count} {label}**")

        if tile_parts:
            response_parts.append(f"Found {', '.join(tile_parts)}.")

        if plan.itinerary_blocks:
            # We have itinerary content from Specialist
            response_parts.append(
                f"I've also added {len(plan.itinerary_blocks)} activities to your itinerary."
            )

        if plan.constraints:
            # Mention specialist constraints
            response_parts.append("I'm keeping the specialist's recommendations in mind.")

        if not response_parts:
            # Default planning response
            response_parts.append(
                f"I'm putting together your trip to {plan.destination}. "
                "Would you like me to search for flight and hotel options?"
            )

        return " ".join(response_parts)


# =============================================================================
# Node Function (for graph registration)
# =============================================================================


async def trip_architect(state: GraphState) -> GraphState:
    """
    TripArchitect node function for LangGraph.

    The "General Agent" that manages the trip plan.
    """
    import logging
    import time

    from app.debug_utils import (
        CompactLogger,
        _debug_log,
        _debug_node_start,
        _debug_node_timer_end,
        _debug_node_timer_start,
    )

    logger = logging.getLogger(__name__)

    # Start timing this node execution
    _debug_node_timer_start("architect")
    node_start_time = time.time()

    # Initialize compact logger with request metrics
    metrics = state.metadata.get("_metrics")
    clog = CompactLogger("architect", metrics=metrics)

    # Get user message
    user_text = ""
    if state.messages:
        last_msg = state.messages[-1]
        if hasattr(last_msg, "content"):
            user_text = last_msg.content

    # ==========================================================================
    # Auto-Fix Loop: Handle retry from ConstraintGuard
    # ==========================================================================
    violations_for_retry = state.metadata.get("violations_for_retry")
    if violations_for_retry:
        state.guard_retry_count += 1
        logger.debug(
            f"Auto-fix retry {state.guard_retry_count}: "
            f"violations={[v['code'] for v in violations_for_retry]}"
        )
        # Store violations for prompt injection, then clear the trigger
        state.metadata["current_violations_to_fix"] = violations_for_retry
        state.metadata["violations_for_retry"] = []

        # PRESERVE TILES on guard retry - don't clear them!
        # Clearing tiles wipes hotels/flights the user already saw.
        # The Architect retry is for constraint fixes (budget/schedule), not tile regeneration.
        # Tiles are only re-fetched if logistics determines they're needed.
        # NOTE: route_after_guard now short-circuits unfixable violations (specialist, route)
        # directly to Synthesizer, so this path only runs for fixable violations.
        # state.tiles = {}  # REMOVED - preserve existing tiles

        # CRITICAL: Reset logistics_attempted so route_after_architect sends us to logistics
        # Without this, tiles stay empty and guard sees nothing to validate
        state.metadata["logistics_attempted"] = False

    _debug_node_start(
        "architect",
        "🏛️",
        intent=state.intent,
        destination=state.trip_plan.destination,
        specialist=state.active_specialist,
        constraints_count=len(state.trip_plan.constraints),
    )

    # Compact logging: node start
    clog.node_start("ARCHITECT", intent=state.intent, dest=state.trip_plan.destination)

    architect = TripArchitect()

    # ==========================================================================
    # Snapshot before extraction (for change tracking)
    # ==========================================================================
    prev_trip_values = {
        "destination": state.trip_plan.destination,
        "origin": state.trip_plan.origin,
        "start_date": state.trip_plan.start_date,
        "end_date": state.trip_plan.end_date,
        "adults": state.trip_plan.adults,
        "children": state.trip_plan.children,
        "budget": state.trip_plan.budget,
    }
    prev_settings = state.metadata.get("extracted_settings", {})

    # ==========================================================================
    # Extract trip fields and settings from user text
    # ==========================================================================

    # Check if Router already extracted fields or user_text is a system trigger.
    # Both cases have nothing useful to extract — skip the ~1s LLM call.
    _SYSTEM_TRIGGERS = {"GENERATE_PLAN_NOW", "BUILD_PLAN", "REFRESH"}
    router_already_extracted = bool(state.metadata.get("router_extracted_fields"))
    is_system_trigger = user_text.strip() in _SYSTEM_TRIGGERS

    # Secondary guard: skip if Router already populated all core fields this turn
    # (catches edge cases where router_extracted_fields wasn't set)
    fields_already_present = bool(
        state.trip_plan.destination
        and state.trip_plan.start_date
        and state.trip_plan.end_date
        and state.metadata.get("router_output")
    )

    if router_already_extracted or is_system_trigger or fields_already_present:
        reason = (
            "Router already extracted"
            if router_already_extracted
            else "system trigger"
            if is_system_trigger
            else "fields already present from router"
        )
        _debug_log(f"Skipping LLM extraction - {reason}")
        state.metadata["router_extracted_fields"] = False
    else:
        # Update trip plan from user text using LLM extraction
        state.trip_plan, field_tokens = await _update_trip_plan_from_llm(state.trip_plan, user_text)
        # Compact logging: LLM call for field extraction
        if field_tokens:
            clog.llm_call(
                model=settings.extraction_model,
                prompt_tokens=field_tokens.get("prompt_tokens", 0),
                completion_tokens=field_tokens.get("completion_tokens", 0),
                purpose="field_extraction",
            )

    if _block_destination_switch_in_architect(state, prev_trip_values.get("destination")):
        return state

    # Detect destination pivot and clear stale state (preserves origin, dates, travelers, budget)
    _detect_and_handle_pivot(state, prev_trip_values.get("destination"))

    # Extract settings if keywords detected (booking toggles, preferences)
    # Skip when: router already extracted fields, system trigger, or router
    # already detected a settings change (SETTINGS_TO_LOGISTICS fast path)
    router_handled_settings = bool(state.metadata.get("router_detected_settings_change"))
    if (
        _has_settings_keywords(user_text)
        and not router_already_extracted
        and not is_system_trigger
        and not router_handled_settings
    ):
        settings_extracted, settings_tokens = await _extract_settings_with_llm(user_text)
        extracted_dict = settings_extracted.model_dump(exclude_none=True)
        if extracted_dict:
            state.metadata["extracted_settings"] = extracted_dict
            if settings_tokens:
                from app.debug_utils import log_tokens

                log_tokens(
                    "ARCHITECT",
                    settings_tokens.get("prompt_tokens", 0),
                    settings_tokens.get("completion_tokens", 0),
                    settings_tokens.get("total_tokens", 0),
                )
                # Compact logging: LLM call for settings extraction
                clog.llm_call(
                    model=settings.extraction_model,
                    prompt_tokens=settings_tokens.get("prompt_tokens", 0),
                    completion_tokens=settings_tokens.get("completion_tokens", 0),
                    purpose="settings_extraction",
                )
            _debug_log(f"Extracted settings: {extracted_dict}")

    # Resolve flexible dates to concrete dates
    state.trip_plan = _resolve_flexible_dates(state.trip_plan, user_text, state.metadata)

    # Auto-toggle flights based on origin presence (implements schemas.py line 328)
    _auto_toggle_flights(
        plan=state.trip_plan,
        prev_origin=prev_trip_values.get("origin"),
        extracted_settings=state.metadata.get("extracted_settings", {}),
        metadata=state.metadata,
    )

    # ==========================================================================
    # Track what changed (for ack_updates)
    # ==========================================================================
    turn_applied_fields = []

    # Track trip field changes
    for field, prev_val in prev_trip_values.items():
        new_val = getattr(state.trip_plan, field, None)
        if new_val != prev_val and new_val is not None:
            turn_applied_fields.append(field)

    # Track settings changes (use dotted notation for UI)
    new_settings = state.metadata.get("extracted_settings", {})
    settings_field_map = {
        "flights_toggle": "booking_types.flights",
        "hotels_toggle": "booking_types.hotels",
        "activities_toggle": "booking_types.activities",
        "ground_transport_toggle": "booking_types.ground_transport",
        "flight_direct_only": "flight_settings.direct_only",
        "flight_cabin_class": "flight_settings.cabin_class",
        "flight_round_trip": "flight_settings.round_trip",
        "hotel_min_stars": "hotel_settings.min_stars",
        "activity_skill_level": "activity_settings.skill_level",
    }
    for extract_key, ui_key in settings_field_map.items():
        if new_settings.get(extract_key) is not None:
            if new_settings.get(extract_key) != prev_settings.get(extract_key):
                turn_applied_fields.append(ui_key)

    if turn_applied_fields:
        state.metadata["turn_applied_fields"] = turn_applied_fields
        state.metadata["prev_trip_values_snapshot"] = prev_trip_values
        _debug_log(f"Fields changed this turn: {turn_applied_fields}")

    # DEBUG: Print trip_plan after extraction
    from app.debug_utils import log

    log(
        "ARCHITECT",
        "Extracted fields",
        data=(
            f"dest={state.trip_plan.destination} | "
            f"dates={state.trip_plan.start_date} to {state.trip_plan.end_date}"
        ),
    )

    # Determine mode
    mode = architect.determine_mode(state)
    state.metadata["architect_mode"] = mode

    _debug_log(f"🏛️ ARCHITECT mode={mode}")

    if mode == "pre_core":
        # S0: Inspiration mode
        response = architect.generate_pre_core_response(state, user_text)
        state.last_summary = response
        state.active_agent_id = "architect"

    elif mode == "missing_fields":
        # Trigger Setup Modal
        missing_response = architect.generate_missing_fields_response(state)
        state.metadata["missing_fields_response"] = missing_response
        state.ui_events.append("MISSING_FIELDS")

        # Generate a friendly prompt
        missing = get_missing_fields(state.trip_plan)
        if "dates" in missing:
            state.last_summary = "Great destination! When are you planning to go?"
        else:
            state.last_summary = "Let's nail down a few more details for your trip."
        _debug_log(f"🏛️ ARCHITECT missing_fields={missing}")

    else:
        # Planning mode
        # Check if we should fetch tiles
        intent = state.intent or "general"
        if architect.should_fetch_tiles(state, intent):
            state.ui_events.append("TILES_LOADING")
            _debug_log("🏛️ ARCHITECT fetching tiles...")
            tiles = await architect.fetch_tiles_for_plan(state)
            state.tiles = tiles
            state.ui_events.append("TILES_READY")
            tile_counts = {k: len(v) for k, v in tiles.items()}
            _debug_log(f"🏛️ ARCHITECT tiles fetched: {tile_counts}")

        response = architect.generate_planning_response(state, user_text)
        state.last_summary = response
        state.active_agent_id = "architect"
        state.trip_plan.status = "planning"

    _debug_node_timer_end(
        "architect",
        "🏛️",
        mode=mode,
        destination=state.trip_plan.destination,
        status=state.trip_plan.status,
        tiles_count=sum(len(v) for v in state.tiles.values()),
        response_len=len(state.last_summary or ""),
    )

    # Compact logging: node end
    duration_ms = int((time.time() - node_start_time) * 1000)
    clog.node_end(
        "ARCHITECT",
        duration_ms,
        mode=mode,
        dest=state.trip_plan.destination,
        tiles=sum(len(v) for v in state.tiles.values()),
    )

    # Mark that architect ran this turn (for post-logistics skip optimization)
    state.metadata["architect_ran_this_turn"] = True

    return state
