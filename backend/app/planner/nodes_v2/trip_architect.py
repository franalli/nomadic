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
import os
from datetime import datetime, timedelta
from typing import Any, Dict, List

from langchain_openai import ChatOpenAI

from app.planner.state import (
    ExtractedSettingsFields,
    ExtractedTripFields,
    GraphStateV2,
    TripPlan,
    create_missing_fields_response,
    get_missing_fields,
    trip_plan_is_ready,
)
from app.tools.tile_service import fetch_travel_tiles

logger = logging.getLogger(__name__)

# =============================================================================
# LLM-Based Field Extraction (No Regex)
# =============================================================================

EXTRACTION_MODEL = os.getenv("EXTRACTION_MODEL", "gpt-4o-mini")


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
    llm = ChatOpenAI(model=EXTRACTION_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(ExtractedTripFields, include_raw=True)

    # Inject current date for relative date resolution
    today = datetime.now()
    today_str = today.strftime("%A, %B %d, %Y")  # "Sunday, January 26, 2026"

    prompt = f"""Extract trip planning fields from the user message.

CURRENT DATE: {today_str}

EXISTING PLAN (for context - don't overwrite unless user explicitly changes):
- Destination: {current_plan.destination or 'Not set'}
- Origin: {current_plan.origin or 'Not set'}
- Dates: {current_plan.start_date or 'Not set'} to {current_plan.end_date or 'Not set'}
- Travelers: {current_plan.adults} adults, {current_plan.children} children
- Budget: {current_plan.budget or 'Not set'}

RULES:
1. Convert ALL relative dates to YYYY-MM-DD format based on CURRENT DATE:
   - "tomorrow" → calculate {(today + timedelta(days=1)).strftime('%Y-%m-%d')}
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

4. Don't change existing values unless user explicitly updates them.
   Exception: If user says "actually Paris" and destination was "London", update it.

USER MESSAGE: {user_text}
"""

    try:
        result = await structured_llm.ainvoke(prompt)
        # Extract parsed result and token usage
        parsed = result["parsed"]
        raw = result["raw"]
        token_usage = {}
        if hasattr(raw, "response_metadata"):
            token_usage = raw.response_metadata.get("token_usage", {})
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

2. FLIGHT SETTINGS:
   - "Direct flights only" / "No layovers" → flight_direct_only: true
   - flight_cabin_class MUST be one of: "economy", "premium_economy", "business", "first"
     - "Business class" → "business"
     - "First class" → "first"
     - "Economy" / "Coach" → "economy"
   - "One way" / "Not round trip" → flight_round_trip: false

3. HOTEL SETTINGS (hotel_min_stars: 0-5):
   - "5 star" / "Luxury" / "Five star" → hotel_min_stars: 5
   - "4 star or better" / "Upscale" → hotel_min_stars: 4
   - "3 star" / "Mid-range" → hotel_min_stars: 3
   - "Budget" / "Cheap" → hotel_min_stars: 0
   - Ambiguous terms like "nice" or "good" → DO NOT set (leave null)

4. Only extract fields EXPLICITLY mentioned. Return null for anything ambiguous.

USER MESSAGE: {user_text}
"""

# Keywords that indicate settings-related content
SETTINGS_KEYWORDS = [
    "flight",
    "flights",
    "hotel",
    "hotels",
    "stay",
    "stays",
    "direct",
    "layover",
    "class",
    "star",
    "activity",
    "activities",
    "turn off",
    "turn on",
    "no need",
    "don't need",
    "include",
    "business",
    "first class",
    "economy",
    "luxury",
    "budget",
    "one way",
    "round trip",
]


async def _extract_settings_with_llm(user_text: str) -> tuple[ExtractedSettingsFields, dict]:
    """
    Use LLM to extract booking settings from user text.

    Only called when settings-related keywords are detected.
    Returns tuple of (ExtractedSettingsFields, token_usage_dict).
    """
    llm = ChatOpenAI(model=EXTRACTION_MODEL, temperature=0)
    structured_llm = llm.with_structured_output(ExtractedSettingsFields, include_raw=True)

    prompt = SETTINGS_EXTRACTION_PROMPT.format(user_text=user_text)

    try:
        result = await structured_llm.ainvoke(prompt)
        parsed = result["parsed"]
        raw = result["raw"]
        token_usage = {}
        if hasattr(raw, "response_metadata"):
            token_usage = raw.response_metadata.get("token_usage", {})
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
    from app.debug_utils import _debug_v2

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
        _debug_v2(f"Auto-resolved flexible dates: {default_start} to {default_end}")

        # Flag for synthesizer to explain the default
        metadata["flexible_date_resolved"] = True
        metadata["resolved_start_date"] = default_start
        metadata["resolved_end_date"] = default_end

    return plan


async def _update_trip_plan_from_llm(
    plan: TripPlan,
    user_text: str,
) -> TripPlan:
    """
    Update trip plan using LLM-extracted fields.

    This replaces the old regex-based _update_trip_plan_from_text().
    """
    from app.debug_utils import _debug_v2

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
    if extracted.destination:
        plan.destination = extracted.destination
        _debug_v2(f"LLM extracted destination: {extracted.destination}")

    if extracted.origin:
        plan.origin = extracted.origin
        _debug_v2(f"LLM extracted origin: {extracted.origin}")

    if extracted.start_date:
        plan.start_date = extracted.start_date
        _debug_v2(f"LLM extracted start_date: {extracted.start_date}")

    if extracted.end_date:
        plan.end_date = extracted.end_date
        _debug_v2(f"LLM extracted end_date: {extracted.end_date}")
    elif extracted.duration_days and extracted.start_date:
        # Calculate end date from duration
        try:
            start = datetime.fromisoformat(extracted.start_date)
            plan.end_date = (start + timedelta(days=extracted.duration_days)).strftime("%Y-%m-%d")
            _debug_v2(
                f"LLM calculated end_date from duration: {plan.end_date} "
                f"({extracted.duration_days} days)"
            )
        except ValueError:
            pass

    if extracted.adults:
        plan.adults = extracted.adults
        plan.travelers = extracted.adults + (extracted.children or plan.children)
        _debug_v2(f"LLM extracted adults: {extracted.adults}")

    if extracted.children is not None:
        plan.children = extracted.children
        plan.travelers = plan.adults + extracted.children
        _debug_v2(f"LLM extracted children: {extracted.children}")

    if extracted.budget:
        plan.budget = extracted.budget
        _debug_v2(f"LLM extracted budget: {extracted.budget}")

    if extracted.trip_type:
        plan.trip_type = extracted.trip_type
        _debug_v2(f"LLM extracted trip_type: {extracted.trip_type}")

    return plan


def _detect_and_handle_pivot(state: "GraphStateV2", old_destination: str | None) -> bool:
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
        self.debug = bool(os.getenv("DEBUG_PLAN_MESSAGES"))

    def determine_mode(self, state: GraphStateV2) -> str:
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

    def generate_pre_core_response(self, state: GraphStateV2, user_text: str) -> str:
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

    def generate_missing_fields_response(self, state: GraphStateV2) -> Dict[str, Any]:
        """
        Generate structured response for missing fields.

        Returns dict that triggers Setup Modal.
        """
        missing_response = create_missing_fields_response(state.trip_plan)

        if missing_response:
            return missing_response.model_dump()

        return {"type": "missing_fields", "fields": [], "message": "Ready to plan!"}

    def should_fetch_tiles(self, state: GraphStateV2, intent: str) -> bool:
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

        # ONLY fetch tiles for booking intent (triggered by "Build plan" button)
        # Do NOT auto-fetch - user must explicitly request plan generation
        if intent == "booking":
            logger.debug("should_fetch_tiles: returning True (booking intent)")
            return True

        logger.debug("should_fetch_tiles: returning False (waiting for Build Plan click)")
        return False

    def fetch_tiles_for_plan(self, state: GraphStateV2) -> Dict[str, List[Dict]]:
        """
        Fetch tiles for the current plan.

        Respects constraints from Specialist.
        """
        plan = state.trip_plan
        tiles_result = {}

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
            # Check if we need origin for flights
            if category == "flights" and not plan.origin:
                logger.debug(f"fetch_tiles_for_plan: skipping {category} (no origin)")
                continue

            logger.debug(f"fetch_tiles_for_plan: fetching {category}...")
            result = fetch_travel_tiles.invoke(
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
                logger.info(f"fetch_tiles_for_plan: {category} returned {tile_count} tiles")
                tiles_result[category] = result.get("tiles", [])
            else:
                logger.warning(
                    f"fetch_tiles_for_plan: {category} failed - {result.get('error', 'unknown')}"
                )

        logger.info(
            "fetch_tiles_for_plan: total tiles = " "{k: len(v) for k, v in tiles_result.items()}"
        )
        return tiles_result

    def generate_planning_response(self, state: GraphStateV2, user_text: str) -> str:
        """
        Generate a planning mode response.

        May include tile fetching results.
        """
        plan = state.trip_plan

        # Simple response based on what we have
        response_parts = []

        if state.tiles:
            # We have tiles to show
            for category, tiles in state.tiles.items():
                if tiles:
                    response_parts.append(f"I found {len(tiles)} {category} options for you.")

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


async def trip_architect(state: GraphStateV2) -> GraphStateV2:
    """
    TripArchitect node function for LangGraph.

    The "General Agent" that manages the trip plan.
    """
    import logging

    from app.debug_utils import _debug_v2, _debug_v2_node_end, _debug_v2_node_start

    logger = logging.getLogger(__name__)

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
        state.metadata["violations_for_retry"] = None
        # Clear previous tiles so we can fetch new ones with corrections
        state.tiles = {}

    _debug_v2_node_start(
        "architect",
        "🏛️",
        intent=state.intent,
        destination=state.trip_plan.destination,
        specialist=state.active_specialist,
        constraints_count=len(state.trip_plan.constraints),
    )

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

    # Update trip plan from user text using LLM extraction
    state.trip_plan = await _update_trip_plan_from_llm(state.trip_plan, user_text)

    # Detect destination pivot and clear stale state (preserves origin, dates, travelers, budget)
    _detect_and_handle_pivot(state, prev_trip_values.get("destination"))

    # Extract settings if keywords detected (booking toggles, preferences)
    if _has_settings_keywords(user_text):
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
            _debug_v2(f"Extracted settings: {extracted_dict}")

    # Resolve flexible dates to concrete dates
    state.trip_plan = _resolve_flexible_dates(state.trip_plan, user_text, state.metadata)

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
        _debug_v2(f"Fields changed this turn: {turn_applied_fields}")

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

    _debug_v2(f"🏛️ ARCHITECT mode={mode}")

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
        _debug_v2(f"🏛️ ARCHITECT missing_fields={missing}")

    else:
        # Planning mode
        # Check if we should fetch tiles
        intent = state.intent or "general"
        if architect.should_fetch_tiles(state, intent):
            state.ui_events.append("TILES_LOADING")
            _debug_v2("🏛️ ARCHITECT fetching tiles...")
            tiles = architect.fetch_tiles_for_plan(state)
            state.tiles = tiles
            state.ui_events.append("TILES_READY")
            tile_counts = {k: len(v) for k, v in tiles.items()}
            _debug_v2(f"🏛️ ARCHITECT tiles fetched: {tile_counts}")

        response = architect.generate_planning_response(state, user_text)
        state.last_summary = response
        state.active_agent_id = "architect"
        state.trip_plan.status = "planning"

    _debug_v2_node_end(
        "architect",
        "🏛️",
        mode=mode,
        destination=state.trip_plan.destination,
        status=state.trip_plan.status,
        tiles_count=sum(len(v) for v in state.tiles.values()),
        response_len=len(state.last_summary or ""),
    )

    return state
