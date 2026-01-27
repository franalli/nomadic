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

V2 Enhancement: Uses LLM for complex planning responses to weave together
Architect, Specialist, and Guard outputs into a coherent narrative.
"""

import logging
import os
from pathlib import Path
from typing import List

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.planner.state import (
    GraphStateV2,
    SynthesizerOutput,
    UIEvent,
)

logger = logging.getLogger(__name__)

# =============================================================================
# LLM Configuration
# =============================================================================

SYNTHESIZER_MODEL = os.getenv("SYNTHESIZER_MODEL", "gpt-4o")


def _get_synthesizer_llm() -> ChatOpenAI:
    """Get the LLM for synthesis with streaming enabled."""
    return ChatOpenAI(
        model=SYNTHESIZER_MODEL,
        temperature=0.7,  # Slightly creative for natural voice
        streaming=True,  # Enable token streaming
        max_tokens=500,  # Keep responses concise
    )


def _load_system_prompt() -> str:
    """Load the synthesizer system prompt from file."""
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "synthesizer.txt"
    if prompt_path.exists():
        return prompt_path.read_text(encoding="utf-8")
    return (
        "You are a helpful travel assistant. "
        "Synthesize the trip information into a friendly response."
    )


def _build_synthesis_context(state: GraphStateV2) -> str:
    """Build context string from all graph sources for LLM synthesis."""
    parts = []
    plan = state.trip_plan

    # Architect mode context - CRITICAL for LLM to know what response to generate
    architect_mode = state.metadata.get("architect_mode", "unknown")
    parts.append("## Current Mode")
    parts.append(f"- Architect mode: {architect_mode}")

    # Plan view state for tone differentiation (Setup vs Plan mode)
    plan_view_state = state.metadata.get("plan_view_state", "S0_BOOTSTRAP")
    is_setup_mode = (
        plan_view_state.startswith("S0")
        or plan_view_state.startswith("S1")
        or plan_view_state.startswith("S2")
    )
    tone_mode = "SETUP" if is_setup_mode else "PLAN"
    parts.append(f"- Plan view state: {plan_view_state}")
    parts.append(f"- Tone mode: {tone_mode}")

    # Flexible date resolution info
    if state.metadata.get("flexible_date_resolved"):
        parts.append("- flexible_date_resolved: true")
        parts.append(f"- resolved_start_date: {state.metadata.get('resolved_start_date')}")
        parts.append(f"- resolved_end_date: {state.metadata.get('resolved_end_date')}")

    # Fields changed this turn (for acknowledgment)
    turn_applied = state.metadata.get("turn_applied_fields", [])
    if turn_applied:
        parts.append(f"- Fields changed this turn: {', '.join(turn_applied)}")

    if architect_mode == "missing_fields":
        missing = state.metadata.get("missing_fields", [])
        if missing:
            parts.append(f"- Missing fields: {', '.join(missing)}")
            parts.append("- YOUR TASK: Ask the user for the missing information naturally")
    elif architect_mode == "pre_core":
        parts.append("- YOUR TASK: Inspire the user and help them explore options")
    elif architect_mode == "core_planning":
        parts.append("- YOUR TASK: Summarize progress and guide to next steps")

    # User's latest message (find the last HumanMessage)
    from langchain_core.messages import HumanMessage

    for msg in reversed(state.messages):
        if isinstance(msg, HumanMessage):
            parts.append("\n## User's Latest Message")
            parts.append(f'"{msg.content}"')
            break

    # Core trip info
    parts.append("\n## TripPlan")
    parts.append(f"- Destination: {plan.destination or 'Not set'}")
    if plan.start_date:
        parts.append(f"- Dates: {plan.start_date} to {plan.end_date or 'TBD'}")
    parts.append(f"- Travelers: {plan.adults} adults, {plan.children} children")
    if plan.budget:
        parts.append(f"- Budget: {plan.currency} {plan.budget}")
    if plan.trip_type:
        parts.append(f"- Trip Type: {plan.trip_type}")

    # Specialist content - COUNTS ONLY (descriptions are in the right panel)
    if plan.itinerary_blocks:
        activity_blocks = [b for b in plan.itinerary_blocks if not getattr(b, "is_buffer", False)]
        buffer_blocks = [b for b in plan.itinerary_blocks if getattr(b, "is_buffer", False)]
        parts.append("\n## Specialist Content (counts only - details on right panel)")
        if activity_blocks:
            parts.append(f"- Activities added: {len(activity_blocks)}")
        if buffer_blocks:
            parts.append(f"- Safety buffers: {len(buffer_blocks)}")
        parts.append("- NOTE: Do NOT describe activities in chat. Just mention counts.")

    # Constraints from specialist
    if plan.constraints:
        parts.append("\n## Active Constraints")
        for c in plan.constraints:
            parts.append(f"- {c.rule}: {c.reason or 'No reason provided'}")

    # Constraint violations from Guard
    if state.constraints_violated:
        parts.append("\n## Constraint Violations (address these naturally!)")
        for v in state.constraints_violated:
            parts.append(f"- {v}")

    # Tile results - COUNTS ONLY (details are in the right panel)
    # Don't include tile names/prices - LLM should only mention counts
    if state.tiles:
        parts.append("\n## Available Options (counts only - details on right panel)")
        tile_counts = []
        for category, tiles in state.tiles.items():
            if tiles:
                tile_counts.append(f"{len(tiles)} {category}")
        if tile_counts:
            parts.append(f"- Found: {', '.join(tile_counts)}")
            parts.append(
                "- NOTE: Do NOT list individual options. "
                "Just mention counts and direct to right panel."
            )

    return "\n".join(parts)


async def synthesize_with_llm(state: GraphStateV2) -> tuple[str | None, dict]:
    """
    Generate response using LLM for coherent synthesis.

    Weaves together Architect, Specialist, and Guard outputs
    into a single, natural-sounding response.

    Returns tuple of (response_content, token_usage_dict).
    """
    llm = _get_synthesizer_llm()
    system_prompt = _load_system_prompt()
    context = _build_synthesis_context(state)

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Synthesize a response for this context:\n\n{context}"),
    ]

    try:
        # Use non-streaming for the node (streaming handled by astream_events)
        response = await llm.ainvoke(messages)
        token_usage = {}
        if hasattr(response, "response_metadata"):
            token_usage = response.response_metadata.get("token_usage", {})
        return response.content, token_usage
    except Exception as e:
        logger.error(f"LLM synthesis failed: {e}")
        # Fall back to template-based response
        return None, {}


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
    elif state.active_specialist or state.metadata.get("last_executed_specialist"):
        topic = state.active_specialist or state.metadata.get("last_executed_specialist")
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
        specialist = state.active_specialist or state.metadata.get("last_executed_specialist")

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
        trip_type = (
            plan.trip_type
            or state.active_specialist
            or state.metadata.get("last_executed_specialist")
            or "travel"
        )
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

    Uses LLM synthesis for planning mode to weave together outputs from
    Architect, Specialist, and Guard into a coherent narrative.
    Template-based for simple greetings (speed optimization).

    True token streaming is captured via astream_events in run_turn_streaming.

    Performance: Image fetch runs in parallel with LLM synthesis to mask latency.
    """
    import asyncio

    from langchain_core.messages import AIMessage

    from app.debug_utils import _debug_v2_node_end, _debug_v2_node_start

    _debug_v2_node_start(
        "synthesizer",
        "📝",
        mode=state.metadata.get("architect_mode"),
        has_tiles=bool(state.tiles),
        has_specialist=bool(
            state.active_specialist or state.metadata.get("last_executed_specialist")
        ),
    )

    # SPECULATIVE MODE: Silent Execution
    # Don't generate a chat message - just emit UI event for frontend to pick up
    # This prevents random chat bubbles appearing while user is typing in Setup
    if state.intent == "speculative":
        from app.debug_utils import log

        log("SYNTH", "🔮 Speculative mode - silent execution, no chat message")
        state.last_summary = ""  # No chat bubble
        state.ui_events.append("SPECIALIST_PREVIEW_READY")
        # Keep suggested_replies unchanged

        _debug_v2_node_end(
            "synthesizer",
            "📝",
            speculative=True,
            message_len=0,
        )
        return state

    synth = Synthesizer()

    # Start image fetch in parallel with LLM synthesis (latency masking)
    image_task = asyncio.create_task(enrich_with_images(state))

    # Determine if we should use LLM synthesis or templates
    use_llm = _should_use_llm_synthesis(state)
    message = ""

    from app.debug_utils import log, log_tokens

    if use_llm:
        # Use LLM for complex planning responses
        logger.debug("Using LLM synthesis for response generation")
        log("SYNTH", "Generating LLM response...")
        llm_response, token_usage = await synthesize_with_llm(state)
        if llm_response:
            message = llm_response
            if token_usage:
                log_tokens(
                    "SYNTH",
                    token_usage.get("prompt_tokens", 0),
                    token_usage.get("completion_tokens", 0),
                    token_usage.get("total_tokens", 0),
                )
        else:
            # Fallback to template
            output = synth.generate_response(state)
            message = output.message
            log("SYNTH", "Using template (LLM failed)")
    else:
        # Use templates for simple responses (greetings, pre-core)
        output = synth.generate_response(state)
        message = output.message
        log("SYNTH", "Using template (no LLM needed)")

    # Wait for image fetch to complete before returning (safety check)
    await image_task

    # Generate suggestion chips (always template-based for consistency)
    suggested_replies = generate_suggested_replies(state)

    # Log response details
    log("SYNTH", f"Response: {len(message)} chars")
    log("SYNTH", f"Suggested replies: {suggested_replies[:3]}")

    # Update state
    state.last_summary = message
    state.suggested_replies = suggested_replies

    # Add AI message to chat history
    state.messages.append(AIMessage(content=message))

    # Collect UI events
    plan = state.trip_plan
    ui_events = [
        UIEvent(
            type="PLAN_READY" if plan.status == "ready" else "PLAN_READY",
            agent_id=state.active_agent_id or "architect",
        )
    ]

    # Store synthesizer output in metadata
    state.metadata["synthesizer_output"] = {
        "message": message,
        "suggested_replies": suggested_replies,
        "ui_events": [e.model_dump() for e in ui_events],
        "used_llm": use_llm,
    }

    _debug_v2_node_end(
        "synthesizer",
        "📝",
        response_len=len(message),
        suggested_replies=suggested_replies,
        used_llm=use_llm,
    )

    return state


def _should_use_llm_synthesis(state: GraphStateV2) -> bool:
    """
    Determine if we should use LLM synthesis or templates.

    PRINCIPLE: Always use LLM for user-facing responses.
    All response text should be controlled via prompts, not hardcoded templates.

    Only skip LLM for:
    - Short-circuit GREETING/RESET responses (simple acknowledgments)

    Everything else should go through LLM to ensure natural, contextual responses.
    """
    # Short-circuit responses (GREETING/RESET) use static responses for speed
    # These are simple acknowledgments, not planning responses
    if state.metadata.get("short_circuit_response"):
        return False

    # Everything else uses LLM - even missing_fields, pre_core, etc.
    # The prompt controls the response style and content
    return True
