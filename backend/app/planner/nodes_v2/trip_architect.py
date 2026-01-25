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
"""

import os
from typing import Any, Dict, List, Optional

from app.planner.state import (
    GraphStateV2,
    TripPlan,
    create_missing_fields_response,
    get_missing_fields,
    trip_plan_is_ready,
)
from app.tools.tile_service import fetch_travel_tiles

# =============================================================================
# Architect Prompt Templates
# =============================================================================

# Pre-Core Mode (S0) - Inspiration before logistics
PRE_CORE_PROMPT = """You are the Trip Architect, a friendly travel planning assistant.

## Current Mode: INSPIRATION (Pre-Core)

The user hasn't provided destination or dates yet. Your job is to:
1. Ask leading questions about their interests ("Beach or mountains?", "Adventure or relaxation?")
2. Provide "vibe" suggestions ("Bali is perfect for divers, Patagonia for hikers")
3. Build intent before collecting logistics

DO NOT demand dates immediately. Be conversational and helpful.

## User Message:
{user_text}

## Current Trip Info:
{trip_info}

Respond naturally. If the user mentions a destination, acknowledge it warmly.
If they're unsure, offer 2-3 destination ideas based on their interests.
"""

# Planning Mode - Core fields available
PLANNING_PROMPT = """You are the Trip Architect, a travel planning assistant.

## Current Mode: PLANNING

You have the core trip details. Your job is to:
1. Build out the trip plan with flights, hotels, and activities
2. Call the fetch_travel_tiles tool when you need real options
3. Respect any constraints from the Diving/Hiking Specialist
4. Keep the user informed of what you're planning

## Trip Plan:
Destination: {destination}
Dates: {start_date} to {end_date}
Travelers: {travelers}
Budget: {budget}

## Specialist Constraints:
{constraints}

## User Message:
{user_text}

## Available Tool:
You can call fetch_travel_tiles to get real flight/hotel/activity options.
Only call it when you have destination AND dates.

Respond with your next action or question.
"""

# Missing Fields Prompt
MISSING_FIELDS_PROMPT = """You are the Trip Architect.

I notice we're missing some key details for your trip:
- {missing_fields_list}

Let me help you fill these in. {question}
"""


# =============================================================================
# Field Extraction
# =============================================================================


def _extract_origin_destination(user_text: str) -> tuple:
    """
    Extract origin and destination from user text.

    Returns (origin, destination) tuple.
    """
    import re

    # Pattern for "from X to Y" (case-insensitive)
    from_to_pattern = r"\bfrom\s+([a-zA-Z][a-zA-Z\s]+?)\s+to\s+([a-zA-Z][a-zA-Z\s]+?)(?:\s|$|,|\.)"
    match = re.search(from_to_pattern, user_text, re.IGNORECASE)
    if match:
        origin = match.group(1).strip().title()
        destination = match.group(2).strip().title()
        return origin, destination

    return None, None


def _extract_destination(user_text: str, current: Optional[str]) -> Optional[str]:
    """
    Extract destination from user text.

    Simple heuristic extraction - in production, use NLP.
    """
    import re

    # Words that are NOT destinations (generic/abstract places)
    NON_DESTINATION_WORDS = {
        "somewhere",
        "anywhere",
        "everywhere",
        "nowhere",
        "go",
        "travel",
        "vacation",
        "trip",
        "holiday",
        "beach",
        "mountain",
        "city",
        "warm",
        "cold",
        "hot",
        "fun",
        "relaxation",
        "adventure",
        "explore",
    }

    def is_valid_destination(text: str) -> bool:
        """Check if extracted text is likely a real destination."""
        words = text.lower().split()
        # Reject if all words are non-destination words
        if all(w in NON_DESTINATION_WORDS for w in words):
            return False
        # Reject if starts with common non-destination words
        if words and words[0] in NON_DESTINATION_WORDS:
            return False
        return True

    # First check for "from X to Y" pattern
    _, dest = _extract_origin_destination(user_text)
    if dest and is_valid_destination(dest):
        return dest

    # If we already have a destination, don't overwrite unless explicit
    if current:
        return current

    # Look for "to X" or "in X" patterns (case-insensitive)
    patterns = [
        r"\bto\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",  # "to Paris" (capitalized)
        r"\bin\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",  # "in Bali" (capitalized)
        r"\bvisit\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",  # "visit Tokyo" (capitalized)
        r"\bgoing\s+to\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\b",  # "going to Dubai" (capitalized)
    ]

    for pattern in patterns:
        match = re.search(pattern, user_text)  # Case-sensitive for proper nouns
        if match:
            candidate = match.group(1).strip()
            if is_valid_destination(candidate):
                return candidate.title()

    return current


def _extract_origin(user_text: str, current: Optional[str]) -> Optional[str]:
    """
    Extract origin from user text.
    """
    # Check for "from X to Y" pattern
    origin, _ = _extract_origin_destination(user_text)
    if origin:
        return origin

    return current


def _extract_dates(
    user_text: str, current_start: Optional[str], current_end: Optional[str]
) -> tuple:
    """
    Extract dates from user text.

    Returns (start_date, end_date) tuple.
    """
    # For MVP, keep existing dates if present
    # In production, use date parsing library
    return current_start, current_end


def _update_trip_plan_from_text(plan: TripPlan, user_text: str) -> TripPlan:
    """
    Update trip plan with any new information from user text.
    """
    from app.debug_utils import _debug_v2

    # Extract origin and destination
    new_origin = _extract_origin(user_text, plan.origin)
    if new_origin:
        plan.origin = new_origin
        _debug_v2(f"Extracted origin: {new_origin}")

    new_dest = _extract_destination(user_text, plan.destination)
    if new_dest:
        plan.destination = new_dest
        if new_dest not in plan.destinations:
            plan.destinations.append(new_dest)
        _debug_v2(f"Extracted destination: {new_dest}")

    # Extract dates (placeholder - use real date parsing)
    start, end = _extract_dates(user_text, plan.start_date, plan.end_date)
    if start:
        plan.start_date = start
    if end:
        plan.end_date = end

    return plan


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
        """
        # Check if user mentioned a destination
        potential_dest = _extract_destination(user_text, None)

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

        Only when:
        - Plan is ready (destination + dates)
        - User asked for options/booking
        - We don't already have fresh tiles
        """
        if not trip_plan_is_ready(state.trip_plan):
            return False

        if intent == "booking":
            return True

        # Check if we have tiles already
        if state.tiles and any(state.tiles.values()):
            return False

        return False

    def fetch_tiles_for_plan(self, state: GraphStateV2) -> Dict[str, List[Dict]]:
        """
        Fetch tiles for the current plan.

        Respects constraints from Specialist.
        """
        plan = state.trip_plan
        tiles_result = {}

        # Build constraints dict from Specialist
        constraints = {}
        for c in plan.constraints:
            constraints[c.rule] = True

        # Fetch each category
        for category in ["hotels", "flights", "activities"]:
            # Check if we need origin for flights
            if category == "flights" and not plan.origin:
                continue

            result = fetch_travel_tiles.invoke(
                {
                    "category": category,
                    "location": plan.destination
                    or (plan.destinations[0] if plan.destinations else ""),
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
                tiles_result[category] = result.get("tiles", [])

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
    from app.debug_utils import _debug_v2, _debug_v2_node_end, _debug_v2_node_start

    # Get user message
    user_text = ""
    if state.messages:
        last_msg = state.messages[-1]
        if hasattr(last_msg, "content"):
            user_text = last_msg.content

    _debug_v2_node_start(
        "architect",
        "🏛️",
        intent=state.intent,
        destination=state.trip_plan.destination,
        specialist=state.active_specialist,
        constraints_count=len(state.trip_plan.constraints),
    )

    architect = TripArchitect()

    # Update trip plan from user text
    state.trip_plan = _update_trip_plan_from_text(state.trip_plan, user_text)

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
