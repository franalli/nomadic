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

Uses LLM for complex planning responses to weave together
Architect, Specialist, and Guard outputs into a coherent narrative.
"""

import logging
import os
from pathlib import Path
from typing import List

from jinja2 import Template
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from app.planner.state import (
    GraphState,
    SynthesizerOutput,
    UIEvent,
    get_trip_settings,
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


def _get_response_type(state) -> str:
    """
    Derive response type from graph state for synthesizer prompt.

    GAP 2 FIX: This enables Jinja2 conditionals in synthesizer.txt
    to scope solver-identity tone to planning modes only.
    """
    meta = state.metadata or {}

    # Check for greeting/reset short circuits
    if meta.get("short_circuit_type") in ("greeting", "reset"):
        return "greeting"

    # Check for exploration mode (pre-destination)
    if meta.get("exploration_mode"):
        return "exploration"

    # Check if specialist just ran (adding diving, hiking, etc.)
    if (
        meta.get("specialist_hint")
        or meta.get("specialist_just_ran")
        or meta.get("last_executed_specialist")
    ):
        return "specialist_update"

    # Check for active planning (has destination)
    if state.trip_plan and state.trip_plan.destination:
        return "planning"

    # Safe default: warm conversational tone
    return "exploration"


def _load_system_prompt(state=None) -> str:
    """
    Load and render the synthesizer system prompt from file.

    If state is provided, renders Jinja2 conditionals based on response_type.
    """
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "synthesizer.txt"
    if not prompt_path.exists():
        return (
            "You are a helpful travel assistant. "
            "Synthesize the trip information into a friendly response."
        )

    prompt_text = prompt_path.read_text(encoding="utf-8")

    # If state provided, render Jinja2 conditionals
    if state is not None:
        try:
            response_type = _get_response_type(state)
            template = Template(prompt_text)
            return template.render(response_type=response_type)
        except Exception as e:
            logger.warning(f"Jinja2 render failed, using raw prompt: {e}")
            return prompt_text

    return prompt_text


def _build_synthesis_context(state: GraphState) -> str:
    """Build context string from all graph sources for LLM synthesis."""
    parts = []
    plan = state.trip_plan

    # Architect mode context - CRITICAL for LLM to know what response to generate
    architect_mode = state.metadata.get("architect_mode", "unknown")
    parts.append("## Current Mode")
    parts.append(f"- Architect mode: {architect_mode}")

    # Planning phase for tone differentiation
    # P0/P1/P2 = gathering/exploring phase (conversational, guiding)
    # P3 = finalized phase (confirming, ready to book)
    plan_view_state = state.metadata.get("plan_view_state", "P0_MINIMAL")
    # Normalize legacy S* values to P* for tone calculation
    if plan_view_state.startswith("S0") or plan_view_state.startswith("S1"):
        plan_view_state = "P0_MINIMAL"
    elif plan_view_state.startswith("S2"):
        plan_view_state = "P1_ENRICHED"
    elif plan_view_state.startswith("S3"):
        plan_view_state = "P3_FINALIZED"
    is_gathering_phase = plan_view_state in ("P0_MINIMAL", "P1_ENRICHED", "P2_LOGISTICS")
    tone_mode = "GATHERING" if is_gathering_phase else "FINALIZING"
    parts.append(f"- Planning phase: {plan_view_state}")
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

    # User's activity selections (from pill UI) — MUST acknowledge, never re-ask
    settings = get_trip_settings(state)
    categories = settings.activity_settings.categories
    if categories:
        parts.append("\n## User's Activity Selections (from UI)")
        parts.append(f"- Selected activities: {', '.join(categories)}")
        parts.append(
            "- IMPORTANT: The user ALREADY selected these via the UI. "
            "Acknowledge naturally (e.g., 'Great picks — diving and surfing "
            "are perfect for Bali'). Do NOT ask what activities they want. "
            "Move on to the next missing field."
        )

    # Specialist content - COUNTS ONLY (descriptions are in the plan view)
    if plan.itinerary_blocks:
        activity_blocks = [b for b in plan.itinerary_blocks if not getattr(b, "is_buffer", False)]
        buffer_blocks = [b for b in plan.itinerary_blocks if getattr(b, "is_buffer", False)]
        parts.append("\n## Specialist Content (counts only - details in plan view)")
        if activity_blocks:
            parts.append(f"- Activities added: {len(activity_blocks)}")
        if buffer_blocks:
            parts.append(f"- Safety buffers: {len(buffer_blocks)}")
        parts.append("- NOTE: Do NOT describe activities in chat. Just mention counts.")

    # Experience tiles count (Tier 2 activities from experience_generator)
    if state.tiles:
        experience_tiles = [
            t
            for t in state.tiles.get("activities", [])
            if isinstance(t, dict) and t.get("source_agent") == "experience_generator"
        ]
        if experience_tiles:
            categories = set()
            for t in experience_tiles:
                cat = (t.get("meta") or {}).get("category", "")
                if cat:
                    categories.add(cat)
            cat_str = f" for {', '.join(sorted(categories))}" if categories else ""
            parts.append(f"- Experience activities: {len(experience_tiles)}{cat_str}")

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

    # Specialist feasibility alerts (trip too short, wrong season, etc.)
    strategy_sections = state.metadata.get("strategy_sections", [])

    # Short-trip warning for safety-critical specialists (e.g., diving with no-fly buffer)
    if plan.start_date and plan.end_date:
        try:
            from datetime import date as _date

            sd = _date.fromisoformat(str(plan.start_date))
            ed = _date.fromisoformat(str(plan.end_date))
            trip_days = (ed - sd).days + 1
            active_specialists = set()
            for s in strategy_sections:
                st = (
                    s.get("specialist_type")
                    if isinstance(s, dict)
                    else getattr(s, "specialist_type", None)
                )
                if st:
                    active_specialists.add(st)
            if "diving" in active_specialists and trip_days <= 3:
                parts.append("\n## ⚠️ SHORT TRIP + DIVING WARNING")
                parts.append(f"- Trip is only {trip_days} day(s) with diving specialist active.")
                parts.append(
                    "- The 24h no-fly buffer consumes the last full day, "
                    "leaving limited time for actual dives."
                )
                parts.append(
                    "YOUR TASK: Warn the user that this trip may be too short "
                    "for meaningful diving. Suggest extending by 1-2 days."
                )
        except (ValueError, TypeError):
            pass  # Dates not parseable — skip warning
    infeasible_sections = [
        s
        for s in strategy_sections
        if (
            s.get("feasibility_status")
            if isinstance(s, dict)
            else getattr(s, "feasibility_status", "feasible")
        )
        == "infeasible"
    ]
    if infeasible_sections:
        parts.append("\n## ⚠️ ACTIVITY INFEASIBLE (address this!)")
        for section in infeasible_sections:
            specialist = (
                section.get("specialist_type")
                if isinstance(section, dict)
                else getattr(section, "specialist_type", "unknown")
            )
            reason = (
                section.get("feasibility_reason")
                if isinstance(section, dict)
                else getattr(section, "feasibility_reason", "")
            )
            suggestion = (
                section.get("alternative_suggestion")
                if isinstance(section, dict)
                else getattr(section, "alternative_suggestion", "")
            )
            parts.append(f"- {specialist.title()}: {reason}")
            if suggestion:
                parts.append(f"  Suggestion: {suggestion}")
        parts.append(
            "YOUR TASK: Explain why the activity can't be scheduled and suggest alternatives."
        )

    # REJECTION ALERT: If route error detected, inject explicit guidance
    constraint_violations = state.metadata.get("constraint_violations", [])
    route_violations = [v for v in constraint_violations if v.get("category") == "route"]
    if route_violations:
        parts.append("\n## ⚠️ REJECTION ALERT (CRITICAL)")
        parts.append("The user's input was REJECTED due to invalid route/destination.")
        for v in route_violations:
            parts.append(f"- Error: {v.get('code')} - {v.get('message')}")
        parts.append("YOUR TASK:")
        parts.append("1. Do NOT generate any itinerary content")
        parts.append("2. Firmly but politely explain WHY the input was rejected")
        parts.append("3. Ask the user to provide a VALID alternative")
        parts.append("4. Keep response under 30 words")

    # SAFETY VIOLATIONS: Blocking constraints (e.g., diving surface interval, altitude)
    # These are non-route violations that affect the itinerary's safety/feasibility.
    # The user MUST be told about them so they can adjust.
    blocking_violations = [
        v
        for v in constraint_violations
        if v.get("severity") == "blocking" and v.get("category") != "route"
    ]
    if blocking_violations:
        parts.append("\n## ⚠️ SAFETY CONSTRAINT VIOLATION")
        for v in blocking_violations:
            parts.append(f"- {v.get('code')}: {v.get('message')}")
        parts.append(
            "YOUR TASK: Mention the safety issue briefly in your response "
            "(1 sentence). Suggest how the user could adjust their plan "
            "(e.g., add a rest day, extend the trip, reorder activities)."
        )

    # Tile results - COUNTS ONLY (details are in the plan view)
    # Don't include tile names/prices - LLM should only mention counts
    if state.tiles:
        parts.append("\n## Available Options (counts only - details in plan view)")
        tile_counts = []
        for category, tiles in state.tiles.items():
            if tiles:
                tile_counts.append(f"{len(tiles)} {category}")
        if tile_counts:
            parts.append(f"- Found: {', '.join(tile_counts)}")
            parts.append("- NOTE: Do NOT list individual options. Just mention counts.")

    return "\n".join(parts)


async def synthesize_with_llm(state: GraphState) -> tuple[str | None, dict]:
    """
    Generate response using LLM for coherent synthesis.

    Weaves together Architect, Specialist, and Guard outputs
    into a single, natural-sounding response.

    Returns tuple of (response_content, token_usage_dict).
    """
    llm = _get_synthesizer_llm()
    system_prompt = _load_system_prompt(state)  # GAP 2: Pass state for Jinja2 rendering
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
        content = response.content
        # Strip wrapping quotes — LLM sometimes mirrors example formatting
        if content and len(content) > 2 and content[0] == '"' and content[-1] == '"':
            content = content[1:-1]
        return content, token_usage
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


def generate_suggestions(state: GraphState) -> List[str]:
    """
    Deterministic suggestion engine.
    Derives all suggestions from router capability registries x current state.
    Returns max 3 executable suggestions. No padding.
    """
    from app.planner.nodes.intent_router import (
        SuggestionPool,
        _build_date_suggestions,
        _build_plan_progression_suggestions,
        _build_question_suggestions,
        _build_specialist_suggestions,
    )

    dest = state.trip_plan.destination or ""

    # ── Step 1: Blocking violations (highest priority) ──
    constraint_violations = state.metadata.get("constraint_violations", [])
    blocking = [
        v
        for v in constraint_violations
        if v.get("severity") == "blocking" and v.get("category") != "route"
    ]
    if blocking:
        first = blocking[0]
        action = first.get("suggested_action", "Adjust your dates")
        return [action, "Change dates", "Change destination"]

    # ── Step 2: Route violations ──
    route_violations = [v for v in constraint_violations if v.get("category") == "route"]
    if route_violations:
        prev_dest = state.trip_plan.destination
        if prev_dest:
            return [f"Back to {prev_dest}", "Different city", "Help me choose"]
        return ["Paris", "Tokyo", "Barcelona"]

    # ── Step 3: Assemble candidate pool ──
    candidates = []
    candidates.extend(SuggestionPool.get_pool())
    candidates.extend(_build_date_suggestions(state))
    candidates.extend(_build_specialist_suggestions(state))
    candidates.extend(_build_plan_progression_suggestions(state))
    candidates.extend(_build_question_suggestions(state))

    # ── Step 4: Filter by state condition ──
    eligible = [c for c in candidates if c["condition"](state)]

    # ── Step 5: Slot allocation ──
    # Slot 1: ACTION (date prompts) — anchors the chip bar
    # Slot 2-3: DISCOVER (specialist, plan progression, question) — rotates
    ACTION_CATS = {"date_prompt", "date_contextual"}
    DISCOVER_PREFIXES = ("specialist_", "plan_", "question_")
    PRIORITY_0_CATS = {"destination_choice", "date_prompt", "date_contextual"}

    actions = sorted(
        [c for c in eligible if c["category"] in ACTION_CATS],
        key=lambda c: c["priority"],
    )
    discovers = sorted(
        [c for c in eligible if c["category"].startswith(DISCOVER_PREFIXES)],
        key=lambda c: c["priority"],
    )
    fallbacks = sorted(
        [c for c in eligible if c["category"] == "change_dest"],
        key=lambda c: c["priority"],
    )
    # Priority-0 groups (destination_choice, date chips) fill all 3 slots
    p0_group = sorted(
        [c for c in eligible if c["category"] in PRIORITY_0_CATS],
        key=lambda c: c["priority"],
    )

    final: list[dict] = []

    if p0_group:
        # Priority 0 fills all slots (destination choices, date prompts)
        seen_cats: dict[str, int] = {}
        for c in p0_group:
            if len(final) >= 3:
                break
            cat = c["category"]
            cnt = seen_cats.get(cat, 0)
            if cnt >= 3:
                continue
            seen_cats[cat] = cnt + 1
            final.append(c)
    else:
        # Slot 1: best action
        if actions:
            final.append(actions[0])

        # Slot 2-3: discovers (max 1 specialist, then plan progression, then questions)
        specialist_used = False
        for d in discovers:
            if len(final) >= 3:
                break
            if d["category"].startswith("specialist_"):
                if specialist_used:
                    continue
                specialist_used = True
            final.append(d)

        # Backfill with fallbacks
        for f in fallbacks:
            if len(final) >= 3:
                break
            final.append(f)

    # ── Step 6: Render templates ──
    month = state.metadata.get("detected_month", "")
    result = []
    for c in final:
        text = c["template"]
        text = text.replace("{destination}", dest)
        text = text.replace("{month}", month)
        result.append(text)

    # ── Step 7: Track shown question types for rotation ──
    shown_qtypes = [
        c["category"].replace("question_", "")
        for c in final
        if c["category"].startswith("question_")
    ]
    if shown_qtypes:
        prev = state.metadata.get("suggested_question_types", [])
        state.metadata["suggested_question_types"] = prev + shown_qtypes

    return result


# =============================================================================
# Image Enrichment
# =============================================================================


async def enrich_with_images(state: GraphState) -> None:
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

    def synthesize_greeting(self, state: GraphState) -> str:
        """Generate greeting response."""
        return GREETING_TEMPLATE

    def synthesize_inspiration(self, state: GraphState) -> str:
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

    def synthesize_planning(self, state: GraphState) -> str:
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

    def synthesize_constraint_warning(self, state: GraphState) -> str:
        """Generate response highlighting constraint violations."""
        warnings = state.constraints_violated

        if not warnings:
            return ""

        if len(warnings) == 1:
            return f"Just a heads up: {warnings[0]}"

        return "A few things to note:\n" + "\n".join(f"• {w}" for w in warnings[:3])

    def generate_response(self, state: GraphState) -> SynthesizerOutput:
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
        suggested_replies = generate_suggestions(state)

        # Collect UI events
        ui_events = [
            UIEvent(
                type="PLAN_READY" if plan.status == "ready" else "PLAN_UPDATE",
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


async def synthesizer(state: GraphState) -> GraphState:
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

    from app.debug_utils import _debug_node_end, _debug_node_start

    _debug_node_start(
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

        _debug_node_end(
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

    try:
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
            # Check if we have a pre-computed response from router (exploration mode)
            short_circuit_type = state.metadata.get("short_circuit_type")
            if short_circuit_type in ("exploration", "soft_transition", "question_answer"):
                # Use the pre-computed response from router - already in state.last_summary
                message = state.last_summary
                log("SYNTH", f"Pre-computed {short_circuit_type} ({len(message)} chars)")
            elif state.metadata.get("origin_just_set"):
                # Origin was just set via chat - use pre-computed message
                message = state.metadata.get("origin_update_message", "")
                # Append flight search results if available
                flights_count = len([t for t in state.tiles.get("flights", []) if t])
                if flights_count > 0:
                    message += f"\n\nFound **{flights_count} flight options** for your trip!"
                log("SYNTH", f"Origin update response ({len(message)} chars)")
            else:
                # Use templates for simple responses (greetings, pre-core)
                output = synth.generate_response(state)
                message = output.message
                log("SYNTH", "Using template (no LLM needed)")
    finally:
        # Always wait for image fetch task to complete or cancel it
        if not image_task.done():
            image_task.cancel()
            try:
                await image_task
            except asyncio.CancelledError:
                pass
        else:
            await image_task

    # Generate suggestion chips (always template-based for consistency)
    suggested_replies = generate_suggestions(state)

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
            type="PLAN_READY" if plan.status == "ready" else "PLAN_UPDATE",
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

    _debug_node_end(
        "synthesizer",
        "📝",
        response_len=len(message),
        suggested_replies=suggested_replies,
        used_llm=use_llm,
    )

    return state


def _should_use_llm_synthesis(state: GraphState) -> bool:
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
