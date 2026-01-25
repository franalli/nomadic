"""
Synthesizer Node - LLM (Writer) unified response generation.

This node takes all the pieces and generates the final user-facing response:
- TripPlan from Architect
- Content blocks from Specialist
- Constraint violations from Guard
- Tile results from TileService

Key responsibilities:
- Consistent voice across all response types
- Always include suggested_replies (suggestion chips)
- Enrich content with images via Unsplash
- Handle constraint violation warnings gracefully

Key Principle: "One voice, regardless of which agents contributed."
"""

import os
from typing import List

from app.planner.state import (
    GraphStateV2,
    SynthesizerOutput,
    UIEvent,
)

# =============================================================================
# Response Templates
# =============================================================================

# Template for greeting responses
GREETING_TEMPLATE = (
    "Hey there! I'm excited to help you plan an amazing trip.\n\n"
    "What kind of adventure are you dreaming of? Beach relaxation, "
    "mountain hiking, cultural exploration, or something else entirely?"
)

# Template for inspiration (pre-core) responses
INSPIRATION_TEMPLATES = {
    "diving": (
        "For diving adventures, {destination} is incredible! "
        "You could explore {activities}. When are you thinking of going?"
    ),
    "hiking": (
        "For hiking, {destination} offers world-class trails! "
        "Consider {activities}. When would you like to go?"
    ),
    "skiing": (
        "For skiing, {destination} has fantastic conditions! "
        "You could try {activities}. What dates work for you?"
    ),
    "default": (
        "I'd love to help you explore {destination}! "
        "There's so much to see and do. When are you planning to travel?"
    ),
}

# Template for planning responses
PLANNING_TEMPLATE = """I'm putting together your {trip_type} trip to {destination}!

{specialist_content}

{tiles_summary}

{constraint_warnings}

What would you like to focus on next?"""

# Template for constraint warnings
CONSTRAINT_WARNING_TEMPLATE = """⚠️ Just a heads up: {warning}"""


# =============================================================================
# Suggestion Chip Generation
# =============================================================================


def generate_suggested_replies(state: GraphStateV2) -> List[str]:
    """
    Generate context-aware suggestion chips.

    Always returns exactly 3 suggestions.
    """
    suggestions = []
    plan = state.trip_plan

    # Based on current state
    if not plan.destination:
        suggestions = ["Beach destination", "Mountain adventure", "City break"]
    elif not plan.start_date:
        suggestions = ["Next week", "Next month", "I'm flexible"]
    elif state.active_specialist:
        topic = state.active_specialist
        if topic == "diving":
            suggestions = ["Add more dives", "Show dive shops", "Check equipment"]
        elif topic == "hiking":
            suggestions = ["Add trail", "Check weather", "Show gear list"]
        elif topic == "skiing":
            suggestions = ["Add ski days", "Book lessons", "Show resorts"]
        else:
            suggestions = ["Add activities", "Change dates", "Show options"]
    elif state.tiles:
        suggestions = ["Show flights", "Show hotels", "Add activities"]
    else:
        suggestions = ["Search options", "Change destination", "Adjust budget"]

    # Ensure exactly 3 suggestions
    while len(suggestions) < 3:
        suggestions.append("Tell me more")
    return suggestions[:3]


# =============================================================================
# Image Enrichment
# =============================================================================


async def enrich_with_images(state: GraphStateV2) -> None:
    """
    Enrich itinerary blocks with images via Unsplash.

    This preserves the premium UI feel.
    """
    try:
        # Import Unsplash service if available
        from app.services.unsplash import get_destination_image
    except ImportError:
        return  # Unsplash not available

    for block in state.trip_plan.itinerary_blocks:
        if not block.image_url:
            try:
                # Get image for block title/location
                search_term = block.title or block.location or state.trip_plan.destination
                if search_term:
                    image_url = await get_destination_image(search_term)
                    if image_url:
                        block.image_url = image_url
            except Exception:
                pass  # Image fetch failed, continue without


# =============================================================================
# Synthesizer Class
# =============================================================================


class Synthesizer:
    """
    Unified response generator.

    Takes all the pieces from other nodes and creates a coherent response.
    """

    def __init__(self):
        self.debug = bool(os.getenv("DEBUG_PLAN_MESSAGES"))

    def synthesize_greeting(self, state: GraphStateV2) -> str:
        """Generate greeting response."""
        return GREETING_TEMPLATE

    def synthesize_inspiration(self, state: GraphStateV2) -> str:
        """Generate inspiration (pre-core) response."""
        plan = state.trip_plan
        specialist = state.active_specialist

        # Get template
        template = INSPIRATION_TEMPLATES.get(specialist, INSPIRATION_TEMPLATES["default"])

        # Build activities string from content blocks
        activities = ""
        if plan.itinerary_blocks:
            activity_titles = [b.title for b in plan.itinerary_blocks[:3]]
            activities = ", ".join(activity_titles)
        else:
            activities = "amazing experiences"

        return template.format(
            destination=plan.destination or "your dream destination",
            activities=activities,
        )

    def synthesize_planning(self, state: GraphStateV2) -> str:
        """Generate planning response."""
        plan = state.trip_plan
        parts = []

        # Opening
        trip_type = plan.trip_type or state.active_specialist or "travel"
        parts.append(f"I'm working on your {trip_type} trip to {plan.destination}!")

        # Specialist content
        if plan.itinerary_blocks:
            block_titles = [b.title for b in plan.itinerary_blocks[:3]]
            parts.append(f"\n\nI've found some great experiences: {', '.join(block_titles)}.")

        # Tiles summary
        if state.tiles:
            tile_counts = []
            for category, tiles in state.tiles.items():
                if tiles:
                    tile_counts.append(f"{len(tiles)} {category}")
            if tile_counts:
                parts.append(f"\n\nI found {', '.join(tile_counts)} options for you.")

        # Constraint warnings
        if state.constraints_violated:
            for warning in state.constraints_violated[:2]:  # Max 2 warnings
                parts.append(f"\n\n⚠️ {warning}")

        # Closing
        parts.append("\n\nWhat would you like to focus on next?")

        return "".join(parts)

    def synthesize_constraint_warning(self, state: GraphStateV2) -> str:
        """Generate response highlighting constraint violations."""
        warnings = state.constraints_violated

        if not warnings:
            return ""

        if len(warnings) == 1:
            return f"Just a heads up: {warnings[0]}"

        return "A few things to note:\n" + "\n".join(f"• {w}" for w in warnings[:3])

    def generate_response(self, state: GraphStateV2) -> SynthesizerOutput:
        """
        Generate the complete synthesized response.
        """
        plan = state.trip_plan
        message = ""

        # Determine response type
        if state.metadata.get("short_circuit_type") == "greeting":
            message = self.synthesize_greeting(state)

        elif not plan.destination:
            message = self.synthesize_greeting(state)

        elif state.metadata.get("architect_mode") == "pre_core":
            message = self.synthesize_inspiration(state)

        else:
            message = self.synthesize_planning(state)

        # Generate suggestion chips
        suggested_replies = generate_suggested_replies(state)

        # Collect UI events
        ui_events = [
            UIEvent(
                type="PLAN_READY" if plan.status == "ready" else "PLAN_READY",
                agent_id=state.active_agent_id or "architect",
            )
        ]

        return SynthesizerOutput(
            message=message,
            suggested_replies=suggested_replies,
            ui_events=ui_events,
        )


# =============================================================================
# Node Function (for graph registration)
# =============================================================================


async def synthesizer(state: GraphStateV2) -> GraphStateV2:
    """
    Synthesizer node function for LangGraph.

    Generates the final user-facing response.
    """
    from langchain_core.messages import AIMessage

    from app.debug_utils import _debug_v2_node_end, _debug_v2_node_start

    _debug_v2_node_start(
        "synthesizer",
        "📝",
        mode=state.metadata.get("architect_mode"),
        has_tiles=bool(state.tiles),
        has_specialist=bool(state.active_specialist),
    )

    synth = Synthesizer()

    # Enrich content with images
    await enrich_with_images(state)

    # Generate response
    output = synth.generate_response(state)

    # Update state
    state.last_summary = output.message
    state.suggested_replies = output.suggested_replies

    # Add AI message to chat history
    state.messages.append(AIMessage(content=output.message))

    # Store synthesizer output in metadata
    state.metadata["synthesizer_output"] = output.model_dump()

    _debug_v2_node_end(
        "synthesizer",
        "📝",
        response_len=len(output.message),
        suggested_replies=output.suggested_replies,
        ui_events=output.ui_events,
    )

    return state
