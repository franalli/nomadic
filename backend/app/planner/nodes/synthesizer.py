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
import re
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, List, Optional

from jinja2 import Template
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.config import settings
from app.planner.llm_factory import extract_json_content, extract_token_usage, get_llm_by_model
from app.planner.specialist_registry import (
    ALL_DISPLAY_ALIASES,
    TIER1_SPECIALIST_NAMES,
    display_name,
)
from app.planner.state import (
    GraphState,
    SynthesizerOutput,
    UIEvent,
    get_trip_settings,
)

logger = logging.getLogger(__name__)


def _get_model_id(llm) -> str:
    """
    Provider-agnostic model identifier.

    OpenAI exposes .model_name, Gemini exposes .model.
    """
    return getattr(llm, "model_name", None) or getattr(llm, "model", "unknown")


# =============================================================================
# LLM Configuration
# =============================================================================

# Model selection by response complexity (env-configurable via .env)
# Note: Greeting responses are gated by _should_use_llm_synthesis() and never reach this logic
_MODEL_BY_COMPLEXITY = {
    "exploration": settings.synthesizer_exploration_model,  # Simple conversational
    "specialist_update": settings.synthesizer_exploration_model,  # Acknowledge specialist + counts
    "planning": settings.synthesizer_planning_model,  # Complex synthesis with constraints
}

# Per-type max_tokens — exploration is terse, planning needs room for constraint reasoning
_MAX_TOKENS_BY_TYPE = {
    "exploration": 200,  # 2-3 sentences, conversational (was 300)
    "specialist_update": 250,  # Ack + counts + room for varied voice (was 200)
    "planning": 350,  # Constraint reasoning + counts (was 600)
}


def _get_synthesizer_llm(response_type: str = "planning"):
    """
    Get the LLM for synthesis based on response complexity.
    Falls back to synthesizer_planning_model for unknown response types.
    """
    model = _MODEL_BY_COMPLEXITY.get(response_type, settings.synthesizer_planning_model)
    max_tokens = _MAX_TOKENS_BY_TYPE.get(response_type, 500)

    return get_llm_by_model(
        model,
        temperature=0.7,  # Slightly creative for natural voice
        streaming=False,  # Node uses ainvoke; graph handles streaming via astream_events
        max_tokens=max_tokens,
    )


# Conversation history depth by response type
_HISTORY_DEPTH_BY_TYPE = {
    "exploration": 4,  # 2 turns (4 messages)
    "specialist_update": 8,  # 4 turns — needs to see prior responses to avoid repetition
    "planning": 8,  # 4 turns (full context)
}


# =============================================================================
# Suggestion Chip Action Routing
# =============================================================================

# Maps suggestion categories to (action_type, action_target) for frontend routing.
# Categories not in this map default to ("send_message", None).
PILL_ACTION_MAP: Dict[str, tuple[str, Optional[str]]] = {
    # Date chips -> open date picker
    "date_prompt": ("open_pill", "dates"),
    "date_contextual": ("open_pill", "dates"),
    # Booking settings -> open respective sheets
    "plan_hotel_stars": ("open_pill", "stays"),
    "plan_hotel_pref": ("open_pill", "stays"),
    "plan_flight_pref": ("trigger_action", "set_direct_flights_only"),
    "plan_flight_direct": ("trigger_action", "set_direct_flights_only"),  # legacy alias
    # Activities -> open activities sheet
    "plan_activity_explore": ("open_pill", "activities"),
    # Budget/Travelers -> open respective sheets
    "plan_budget": ("open_pill", "budget"),
    "plan_travelers": ("open_pill", "travelers"),
    # Booking discovery chips
    "plan_flights_hint": ("open_pill", "origin"),
    "plan_hotels_compare": ("send_message", None),
}


def _get_response_type(state) -> str:
    """
    Derive response type from graph state for synthesizer prompt.

    GAP 2 FIX: This enables Jinja2 conditionals in synthesizer.txt
    to scope solver-identity tone to planning modes only.

    Uses flag-based classification to avoid fragile turn counting.
    """
    meta = state.metadata or {}

    # Gate-blocked: use planning model (gemini-2.5-flash) for natural explanation
    if meta.get("short_circuit_type") == "gate_blocked":
        return "planning"

    # Check for greeting/reset short circuits
    if meta.get("short_circuit_type") in ("greeting", "reset"):
        return "greeting"

    has_full_trip = (
        state.trip_plan
        and state.trip_plan.destination
        and state.trip_plan.start_date
        and state.trip_plan.end_date
    )

    # Detect significant changes that warrant full planning-depth response
    # even after the first plan has been given.
    turn_applied = meta.get("turn_applied_fields", [])
    added_cats = meta.get("added_categories", [])
    has_structural_change = (
        meta.get("specialist_just_ran")
        or meta.get("constraint_violations")
        or any(f in turn_applied for f in ("start_date", "end_date"))
    )
    has_significant_change = has_structural_change or len(added_cats) > 0

    logger.info(
        "[SYNTH_ROUTE] turn_applied=%s added_cats=%s "
        "planning_given=%s has_full_trip=%s has_sig_change=%s",
        turn_applied,
        added_cats,
        meta.get("_planning_response_given"),
        has_full_trip,
        has_significant_change,
    )

    # Category-only additions after plan is shown → terse specialist_update
    # so the NEW_CATEGORY directive fires (gated on specialist_update type).
    if (
        has_full_trip
        and meta.get("_planning_response_given")
        and len(added_cats) > 0
        and not has_structural_change
    ):
        return "specialist_update"

    # Planning mode: constraint violations with material plan change
    if meta.get("constraint_violations") and has_full_trip:
        if has_significant_change or not meta.get("_planning_response_given"):
            state.metadata["_planning_response_given"] = True
            return "planning"

    # Planning mode: first time all core fields are set OR significant re-plan
    if has_full_trip and (not meta.get("_planning_response_given") or has_significant_change):
        state.metadata["_planning_response_given"] = True
        return "planning"

    # Check for exploration mode (pre-destination)
    if meta.get("exploration_mode"):
        return "exploration"

    # Specialist ran but no significant structural change — terse ack
    if (
        meta.get("specialist_hint")
        or meta.get("specialist_just_ran")
        or meta.get("last_executed_specialist")
    ):
        return "specialist_update"

    # Active planning (has destination, no significant change)
    if state.trip_plan and state.trip_plan.destination:
        return "specialist_update"

    # Safe default: warm conversational tone
    return "exploration"


@lru_cache(maxsize=1)
def _load_prompt_template() -> Template:
    """
    Load and compile Jinja2 template (cached).
    Cache invalidation: Process restart only.
    """
    prompt_path = Path(__file__).parent.parent.parent / "prompts" / "synthesizer.txt"
    if not prompt_path.exists():
        fallback = (
            "You are a helpful travel assistant. "
            "Synthesize the trip information into a friendly response."
        )
        return Template(fallback)

    prompt_text = prompt_path.read_text(encoding="utf-8")
    return Template(prompt_text)


@lru_cache(maxsize=4)
def _render_prompt_for_response_type(response_type: str) -> str:
    """
    Render prompt template for specific response_type (cached).

    Cache size: 4 (greeting/exploration/specialist_update/planning)

    SAFETY: This cache assumes response_type is the ONLY variable passed to template.render().
    If you add more Jinja2 variables in the future, this cache will serve stale content.
    Current: template.render(response_type=response_type) ✓
    """
    template = _load_prompt_template()
    try:
        return template.render(response_type=response_type)
    except Exception as e:
        logger.warning(f"Jinja2 render failed for response_type={response_type}: {e}")
        return template.source if hasattr(template, "source") else str(template)


def _load_system_prompt(state=None) -> str:
    """
    Load and render the synthesizer system prompt.
    Uses cached template loading and rendering for performance.
    """
    if state is None:
        template = _load_prompt_template()
        return template.source if hasattr(template, "source") else str(template)

    # Get response type and use cached rendered prompt
    response_type = _get_response_type(state)
    return _render_prompt_for_response_type(response_type)


def _build_synthesis_context(state: GraphState, response_type: str | None = None) -> str:
    """
    Build context string from all graph sources for LLM synthesis.

    Args:
        state: Current graph state
        response_type: Response type for history depth selection (auto-detected if None)
    """
    parts = []
    plan = state.trip_plan
    meta = state.metadata or {}

    # Diagnostic: log what the synthesizer receives as context signals
    turn_applied = meta.get("turn_applied_fields", [])
    added_cats = meta.get("added_categories", [])
    logger.info(
        "[SYNTH_CONTEXT] response_type=%s turn_applied=%s added_cats=%s "
        "specialist_just_ran=%s planning_given=%s requested_already_active=%s",
        response_type,
        turn_applied,
        added_cats,
        meta.get("specialist_just_ran"),
        meta.get("_planning_response_given"),
        meta.get("requested_already_active"),
    )

    # Architect mode context - CRITICAL for LLM to know what response to generate
    architect_mode = meta.get("architect_mode", "unknown")
    parts.append("## Current Mode")
    parts.append(f"- Architect mode: {architect_mode}")

    # Planning phase for tone differentiation
    # P0/P1/P2 = gathering/exploring phase (conversational, guiding)
    # P3 = finalized phase (confirming, ready to book)
    plan_view_state = meta.get("plan_view_state", "P0_MINIMAL")
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
    if meta.get("flexible_date_resolved"):
        parts.append("- flexible_date_resolved: true")
        parts.append(f"- resolved_start_date: {meta.get('resolved_start_date')}")
        parts.append(f"- resolved_end_date: {meta.get('resolved_end_date')}")

    # Fields changed this turn (for acknowledgment).
    # Filter out auto-bumped date fields — these are internal router
    # adjustments (past→future year bump), not user-initiated changes.
    if meta.get("date_auto_adjustments"):
        turn_applied = [f for f in turn_applied if f not in ("start_date", "end_date")]
    if turn_applied:
        parts.append(f"- Fields changed this turn: {', '.join(turn_applied)}")

    if added_cats:
        parts.append(f"- NEW categories this turn: {', '.join(added_cats)}")

    already_active = meta.get("requested_already_active", [])
    if already_active:
        parts.append(
            f"- User requested {', '.join(already_active)} but "
            f"{'it was' if len(already_active) == 1 else 'they were'} already active. "
            f"Do NOT say {'it was' if len(already_active) == 1 else 'they were'} added."
        )

    # Inject change_type signal for specialist_update prompt routing
    if response_type == "specialist_update":
        last_human = None
        for msg in reversed(state.messages[-4:]):
            if isinstance(msg, HumanMessage):
                last_human = msg.content
                break

        if last_human and last_human.strip() == "GENERATE_PLAN_NOW":
            parts.append("- change_type: STEPPER_RERUN")
        elif state.metadata.get("settings_just_updated"):
            parts.append("- change_type: SETTINGS_CHANGE")
        elif added_cats:
            parts.append("- change_type: NEW_CATEGORY")
        elif turn_applied and any(f in turn_applied for f in ("start_date", "end_date")):
            parts.append("- change_type: DATE_CHANGE")
        else:
            parts.append("- change_type: PLAN_UPDATE")

    # Include previous values when dates changed (for "extended by X days" copy)
    if turn_applied:
        prev_snapshot = state.metadata.get("prev_trip_values_snapshot", {})
        date_fields = [f for f in turn_applied if f in ("start_date", "end_date")]
        if prev_snapshot and date_fields:
            old_end = prev_snapshot.get("end_date")
            new_end = plan.end_date
            if old_end and new_end:
                try:
                    from datetime import datetime

                    old_dt = datetime.strptime(str(old_end)[:10], "%Y-%m-%d")
                    new_dt = datetime.strptime(str(new_end)[:10], "%Y-%m-%d")
                    delta = (new_dt - old_dt).days
                    if delta > 0:
                        parts.append(
                            f"- Trip extended by {delta} days"
                            f" (was {prev_snapshot.get('start_date')} to {old_end},"
                            f" now {plan.start_date} to {new_end})"
                        )
                    elif delta < 0:
                        parts.append(
                            f"- Trip shortened by {abs(delta)} days"
                            f" (was {prev_snapshot.get('start_date')} to {old_end},"
                            f" now {plan.start_date} to {new_end})"
                        )
                except (ValueError, TypeError):
                    pass

    if architect_mode == "missing_fields":
        missing = state.metadata.get("missing_fields", [])
        if missing:
            parts.append(f"- Missing fields: {', '.join(missing)}")
            parts.append("- YOUR TASK: Ask the user for the missing information naturally")
    elif architect_mode == "pre_core":
        trip_type = plan.trip_type
        if trip_type and not plan.destination:
            parts.append(f"- Trip preference detected: {trip_type}")
            parts.append(
                f"- YOUR TASK: The user wants a {trip_type} trip "
                f"but hasn't picked a destination yet. "
                f"Suggest 2-3 specific {trip_type} destinations "
                f"with a brief reason for each. "
                f"Keep it concise (2-3 sentences). "
                f"Do NOT ask an open question like "
                f"'where do you want to go?'"
            )
        else:
            parts.append("- YOUR TASK: Inspire the user and help them explore options")
    elif architect_mode == "core_planning":
        parts.append("- YOUR TASK: Summarize progress and guide to next steps")

    # Conversation history — gives LLM awareness of what was already said
    # Auto-detect response type if not provided
    if response_type is None:
        response_type = _get_response_type(state)

    # Get history depth for this response type
    history_depth = _HISTORY_DEPTH_BY_TYPE.get(response_type, 8)
    recent = state.messages[-history_depth:] if history_depth > 0 else []

    # Count ALL prior assistant turns (not just visible history window)
    turn_count = sum(1 for m in state.messages if isinstance(m, AIMessage))

    if recent:
        parts.append("\n## Conversation History (last few turns)")
        for msg in recent:
            if isinstance(msg, HumanMessage):
                parts.append(f"USER: {msg.content}")
            elif isinstance(msg, AIMessage):
                parts.append(f"ASSISTANT: {msg.content}")
        parts.append(f"\n- Turn number: {turn_count + 1}")
        parts.append(
            "- CRITICAL: Do NOT repeat information OR sentence structure from "
            "previous ASSISTANT messages. Vary your opening, sentence shape, "
            "and flow. If your last response started with 'Your [dest] adventure', "
            "do NOT open that way again. If you already mentioned tile counts, "
            "constraints, or warnings, skip them. Acknowledge only what is NEW."
        )

    # Core trip info
    parts.append("\n## TripPlan")
    parts.append(f"- Destination: {plan.destination or 'Not set'}")
    if plan.start_date:
        parts.append(f"- Dates: {plan.start_date} to {plan.end_date or 'TBD'}")
    # NOTE: date_auto_adjustments (past→future year bump) is an internal
    # router convenience — never surface it to the user. The final dates
    # on trip_plan are already correct; the LLM only needs those.
    parts.append(f"- Travelers: {plan.adults} adults, {plan.children} children")
    if plan.budget:
        parts.append(f"- Budget: {plan.currency} {plan.budget}")
    if plan.budget and state.tiles:
        budget_parts = []
        grand_total = 0.0
        for cat, cat_tiles in state.tiles.items():
            if not isinstance(cat_tiles, list):
                continue
            cat_total = sum(
                t.get("price_estimate") or t.get("live_price") or 0
                for t in cat_tiles
                if isinstance(t, dict)
            )
            if cat_total > 0:
                allocation = plan.budget * {
                    "flights": 0.30,
                    "hotels": 0.40,
                    "activities": 0.30,
                }.get(cat, 0.25)
                status = "over" if cat_total > allocation else "within"
                budget_parts.append(
                    f"  - {display_name(cat)}: ${cat_total:.0f} / ${allocation:.0f} "
                    f"allocated ({status} budget)"
                )
                grand_total += cat_total
        if budget_parts:
            remaining = plan.budget - grand_total
            parts.append(
                f"- Budget breakdown (${grand_total:.0f} of ${plan.budget:.0f} used, "
                f"${remaining:.0f} remaining):"
            )
            parts.extend(budget_parts)
    if plan.trip_type:
        parts.append(f"- Trip Type: {plan.trip_type}")

    settings = get_trip_settings(state)
    flights_requested = settings.booking_types.flights != "off"
    flights_found = len([t for t in state.tiles.get("flights", []) if t]) if state.tiles else 0
    flight_search_status = state.metadata.get("flight_search_status")
    flight_skip_reason = state.metadata.get("flight_skip_reason")
    parts.append("\n## Flight Search")
    parts.append(f"- flights_requested: {flights_requested}")
    parts.append(f"- origin_present: {bool(plan.origin)}")
    parts.append(f"- flights_found: {flights_found}")
    if flight_search_status:
        parts.append(f"- status: {flight_search_status}")
    if flight_skip_reason:
        parts.append(f"- skip_reason: {flight_skip_reason}")
    if flight_skip_reason == "no_origin_for_flights":
        parts.append(
            "- CRITICAL: Do NOT claim flights were found. Ask for the user's departure city."
        )
    elif flights_requested and flights_found == 0:
        parts.append("- CRITICAL: Do NOT claim flight counts when no flights are available.")

    # User's activity selections (from pill UI) — MUST acknowledge, never re-ask
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

    # Day preferences (user-specified activity day counts)
    day_prefs = settings.activity_settings.day_preferences
    if day_prefs:
        prefs_str = ", ".join(f"{k}: {v} days" for k, v in day_prefs.items())
        parts.append("\n## Activity Day Allocations (user-requested)")
        parts.append(f"- {prefs_str}")
        parts.append(
            "- Acknowledge these naturally (e.g., '3 days of diving and 2 days of hiking — "
            "great balance'). Do NOT re-ask how many days."
        )

    # Per-specialist actual activity counts from strategy sections (metadata-backed).
    # This is more accurate than day_preferences for "what was added this turn" phrasing.
    sections = state.metadata.get("strategy_sections", [])
    spec_counts: Dict[str, int] = {}
    for section in sections:
        specialist_type = (
            section.get("specialist_type")
            if isinstance(section, dict)
            else getattr(section, "specialist_type", None)
        )
        if not specialist_type or specialist_type == "local_expert":
            continue

        content_added = (
            section.get("content_added")
            if isinstance(section, dict)
            else getattr(section, "content_added", [])
        )
        count = len(content_added) if content_added else 0
        if count > 0:
            spec_counts[specialist_type] = count

    if spec_counts:
        counts_str = ", ".join(f"{k}: {v}" for k, v in spec_counts.items())
        parts.append("\n## What Changed This Turn")
        parts.append(f"- Specialist activities placed: {counts_str}")
        parts.append("- Mention what changed, not inventory. Counts are context, not copy.")

    # Specialist content — totals for grounding only (plan view has details)
    if plan.itinerary_blocks:
        activity_blocks = [b for b in plan.itinerary_blocks if not getattr(b, "is_buffer", False)]
        buffer_blocks = [b for b in plan.itinerary_blocks if getattr(b, "is_buffer", False)]
        if activity_blocks:
            parts.append(f"- Total specialist activities in plan: {len(activity_blocks)}")
        if buffer_blocks:
            parts.append(f"- Safety buffers in plan: {len(buffer_blocks)}")
        parts.append("- NOTE: Do NOT list or count activities in chat. Describe what changed.")

    # Builder drop reporting — tell user when activities couldn't fit
    drop_ratio = state.metadata.get("last_builder_drop_ratio", 0.0)
    if drop_ratio > 0 and state.metadata.get("last_builder_success"):
        input_count = state.metadata.get("builder_activities_input", 0)
        placed_count = state.metadata.get("builder_activities_placed", 0)
        if input_count > 0 and placed_count < input_count:
            dropped = input_count - placed_count
            parts.append(
                f"- Activity placement: {placed_count} of {input_count} specialist "
                f"activities placed ({dropped} couldn't fit in available days)"
            )
            parts.append(
                "- NOTE: Mention this naturally (e.g., 'I've placed 4 of 6 activities "
                "— extending your trip by a couple days would fit them all')."
            )

    # Builder scheduling conflicts — surface for conversational mention
    builder_conflicts = state.metadata.get("builder_conflicts", [])
    if builder_conflicts:
        parts.append("\n## Scheduling Conflicts")
        for c in builder_conflicts:
            day_str = f"Day {c['day']}: " if c.get("day") else ""
            parts.append(f"- {day_str}{c['message']}")
        parts.append(
            "- Mention these naturally if severe (e.g., "
            "'Day 9 is packed — consider spreading activities')"
        )

    # Experience tiles count (Tier 2 activities from experience_generator)
    # Per-category breakdown prevents LLM from hallucinating counts
    if state.tiles:
        experience_tiles = [
            t
            for t in state.tiles.get("activities", [])
            if isinstance(t, dict) and t.get("source_agent") == "experience_generator"
        ]
        if experience_tiles:
            cat_counts: dict[str, int] = {}
            for t in experience_tiles:
                cat = (t.get("meta") or {}).get("category", "")
                if cat:
                    cat_counts[cat] = cat_counts.get(cat, 0) + 1
            breakdown = ", ".join(f"{v} {k}" for k, v in sorted(cat_counts.items()))
            parts.append(f"- Experience activities: {len(experience_tiles)} total ({breakdown})")

    # Constraints from specialist
    if plan.constraints:
        parts.append("\n## Active Constraints")
        for c in plan.constraints:
            parts.append(f"- {c.rule}: {c.reason or 'No reason provided'}")

    # Constraint violations from Guard (structured format with reasoning)
    constraint_violations_meta = state.metadata.get("constraint_violations", [])
    if constraint_violations_meta:
        budget_violations = [v for v in constraint_violations_meta if v.get("category") == "budget"]
        other_violations = [
            v for v in constraint_violations_meta if v.get("category") not in ("budget", "route")
        ]

        if budget_violations:
            parts.append("\n## Budget Issue (address naturally — no system jargon)")
            for v in budget_violations:
                parts.append(f"- {v.get('message', '')}")
                if v.get("suggested_action"):
                    parts.append(f"  Suggested fix: {v['suggested_action']}")
            parts.append(
                "YOUR TASK: Mention the budget issue conversationally "
                "(e.g., 'The current options run about $X over budget — "
                "I can look for more affordable hotels if you'd like'). "
                "Do NOT use words like 'violation', 'exceeded', 'constraint'."
            )

        if other_violations:
            parts.append("\n## Constraint Alerts (address these naturally!)")
            for v in other_violations:
                parts.append(f"- {v.get('code', '')}: {v.get('message', '')}")
                if v.get("suggested_action"):
                    parts.append(f"  Suggested fix: {v['suggested_action']}")
    elif state.constraints_violated:
        # Fallback: plain string list (older sessions without metadata)
        parts.append("\n## Constraint Violations (address these naturally!)")
        for v in state.constraints_violated:
            parts.append(f"- {v}")

    # --- Input gate violations (blocking) ---
    gate_violations = state.metadata.get("input_gate_violations", [])
    if gate_violations:
        parts.append("\n## Input Validation Issue")
        parts.append("The user's request has problems that prevent planning:")
        for v in gate_violations:
            line = f"- {v['message']}"
            if v.get("suggested_action"):
                line += f" {v['suggested_action']}"
            parts.append(line)
        parts.append(
            "Explain the issue naturally and ask them to adjust. "
            "Do NOT proceed with planning. Do NOT use words like "
            "'validation', 'gate', or 'constraint'."
        )

    # --- Input gate warnings ---
    gate_warnings = state.metadata.get("input_gate_warnings", [])
    if gate_warnings:
        parts.append("\n## Input Notes")
        for w in gate_warnings:
            line = f"- {w['message']}"
            if w.get("suggested_action"):
                line += f" {w['suggested_action']}"
            parts.append(line)
        parts.append("Mention these notes naturally in your response.")

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
            parts.append(f"- {display_name(specialist)}: {reason}")
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


_TILE_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "flights": ("flight", "flights"),
    "hotels": ("hotel", "hotels"),
    "activities": ("activity", "activities"),
}

_TILE_CLAIM_VERB_PATTERN = re.compile(r"\b(found|showing|added|matches|now showing)\b")

_ACTIVITY_CLAIM_VERB_PATTERN = re.compile(
    r"\b(add(?:ed|ing)?|include(?:d|s|ing)?|featur(?:e|ed|es|ing)|with|plus)\b",
    re.IGNORECASE,
)


def _get_active_categories(state: GraphState) -> set[str]:
    """Active categories from state — whatever's been accepted is known."""
    settings = get_trip_settings(state)
    return set(settings.activity_settings.categories) | set(TIER1_SPECIALIST_NAMES)


_GENERIC_ACTIVITY_ENTITY_WORDS = {
    "day",
    "days",
    "night",
    "nights",
    "hotel",
    "hotels",
    "flight",
    "flights",
    "activity",
    "activities",
    "spot",
    "spots",
    "session",
    "sessions",
    "class",
    "classes",
    "option",
    "options",
    "plan",
    "trip",
}

_ACTIVITY_COUNT_LABELS: dict[str, tuple[str, str]] = {
    "nightlife": ("nightlife spot", "nightlife spots"),
    "yoga": ("yoga session", "yoga sessions"),
}

_DAY_PREF_RECAP_PATTERN = re.compile(r"\*\*\d+\s+days?\s+of\s+[^*]+\*\*", re.IGNORECASE)


def _extract_claimed_tile_categories(sentence: str) -> set[str]:
    lowered = (sentence or "").lower()
    has_count = bool(re.search(r"\b\d+\b", lowered))
    has_claim_verb = bool(_TILE_CLAIM_VERB_PATTERN.search(lowered))
    has_option_hint = "option" in lowered
    if not (has_count or has_claim_verb or has_option_hint):
        return set()

    claimed: set[str] = set()
    for category, keywords in _TILE_CATEGORY_KEYWORDS.items():
        if any(kw in lowered for kw in keywords):
            claimed.add(category)
    return claimed


def _canonicalize_activity_category(label: str) -> str:
    cleaned = " ".join((label or "").strip().lower().split())
    if not cleaned:
        return ""
    return ALL_DISPLAY_ALIASES.get(cleaned, cleaned)


def _collect_allowed_activity_categories(state: GraphState) -> set[str]:
    settings = get_trip_settings(state)
    allowed: set[str] = set()

    for category in settings.activity_settings.categories:
        canonical = _canonicalize_activity_category(str(category))
        if canonical:
            allowed.add(canonical)

    for category in settings.activity_settings.day_preferences:
        canonical = _canonicalize_activity_category(str(category))
        if canonical:
            allowed.add(canonical)

    for category in state.metadata.get("added_categories", []) or []:
        canonical = _canonicalize_activity_category(str(category))
        if canonical:
            allowed.add(canonical)

    for section in state.metadata.get("strategy_sections", []) or []:
        specialist_type = (
            section.get("specialist_type")
            if isinstance(section, dict)
            else getattr(section, "specialist_type", None)
        )
        if not specialist_type:
            continue
        canonical = _canonicalize_activity_category(str(specialist_type))
        if canonical and canonical != "local_expert":
            allowed.add(canonical)

    activities = state.tiles.get("activities", []) if state.tiles else []
    for tile in activities:
        if not isinstance(tile, dict):
            continue
        meta = tile.get("meta")
        tile_category = meta.get("category") if isinstance(meta, dict) else tile.get("category")
        canonical = _canonicalize_activity_category(str(tile_category or ""))
        if canonical:
            allowed.add(canonical)

    return allowed


def _extract_activity_mentions(sentence: str, known_categories: set[str]) -> set[str]:
    lowered = (sentence or "").lower()
    mentioned: set[str] = set()

    for category in known_categories:
        if re.search(rf"\b{re.escape(category)}\b", lowered):
            mentioned.add(category)

    for alias, canonical in ALL_DISPLAY_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", lowered):
            mentioned.add(canonical)

    return mentioned


def _normalize_entity_text(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9\s]", " ", (value or "").lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _collect_known_activity_entities(state: GraphState) -> set[str]:
    entities: set[str] = set()

    activities = state.tiles.get("activities", []) if state.tiles else []
    for tile in activities:
        if not isinstance(tile, dict):
            continue
        title = tile.get("title")
        normalized = _normalize_entity_text(str(title or ""))
        if normalized:
            entities.add(normalized)

    for section in state.metadata.get("strategy_sections", []) or []:
        content_added = (
            section.get("content_added")
            if isinstance(section, dict)
            else getattr(section, "content_added", None)
        )
        if not isinstance(content_added, list):
            continue
        for block in content_added:
            title = block.get("title") if isinstance(block, dict) else getattr(block, "title", None)
            normalized = _normalize_entity_text(str(title or ""))
            if normalized:
                entities.add(normalized)

    return entities


def _collect_activity_tile_counts_by_category(state: GraphState) -> dict[str, int]:
    counts: dict[str, int] = {}
    activities = state.tiles.get("activities", []) if state.tiles else []
    for tile in activities:
        if not isinstance(tile, dict):
            continue
        meta = tile.get("meta")
        raw_category = meta.get("category") if isinstance(meta, dict) else tile.get("category")
        category = _canonicalize_activity_category(str(raw_category or ""))
        if not category:
            continue
        counts[category] = counts.get(category, 0) + 1
    return counts


def _extract_named_entity_claims(sentence: str, known_categories: set[str]) -> list[str]:
    claims: list[str] = []
    for bolded in re.findall(r"\*\*([^*]+)\*\*", sentence or ""):
        normalized = _normalize_entity_text(bolded)
        if not normalized:
            continue
        if any(ch.isdigit() for ch in normalized):
            continue
        words = set(normalized.split())
        if len(words) < 2:
            continue
        if words & _GENERIC_ACTIVITY_ENTITY_WORDS:
            continue
        if words & known_categories:
            continue
        claims.append(normalized)
    return claims


def _entity_matches_known_activity(entity: str, known_entities: set[str]) -> bool:
    return any(entity in known or known in entity for known in known_entities)


def _strip_additive_activity_fragment(sentence: str) -> str:
    trimmed = re.sub(
        (
            r"(?:[,;:\-]\s*|\s+)"
            r"(?:add(?:ed|ing)?|include(?:d|s|ing)?|featur(?:e|ed|es|ing)|with|plus)\b.*$"
        ),
        "",
        sentence,
        flags=re.IGNORECASE,
    ).strip()
    if trimmed and trimmed != sentence:
        return trimmed.rstrip(" ,;:-")

    if re.match(
        r"^\s*(?:add(?:ed|ing)?|include(?:d|s|ing)?|featur(?:e|ed|es|ing)|with|plus)\b",
        sentence,
        flags=re.IGNORECASE,
    ):
        return ""

    return sentence.strip()


def _build_authoritative_activity_category_sentence(
    categories: set[str],
    category_counts: dict[str, int],
) -> str:
    if not categories:
        return ""

    parts: list[str] = []
    for category in sorted(categories):
        count = category_counts.get(category, 0)
        if count <= 0:
            continue
        singular, plural = _ACTIVITY_COUNT_LABELS.get(
            category,
            (f"{category} activity", f"{category} activities"),
        )
        label = singular if count == 1 else plural
        parts.append(f"**{count} {label}**")

    if not parts:
        return ""
    if len(parts) == 1:
        return f"Added {parts[0]}."
    if len(parts) == 2:
        return f"Added {parts[0]} and {parts[1]}."
    return f"Added {', '.join(parts[:-1])}, and {parts[-1]}."


def _ground_activity_claims(message: str, state: GraphState) -> str:
    grounded = (message or "").strip()
    if not grounded:
        return grounded

    allowed = _collect_allowed_activity_categories(state)
    if not allowed:
        return grounded

    active_cats = _get_active_categories(state)
    category_counts = _collect_activity_tile_counts_by_category(state)
    known_entities = _collect_known_activity_entities(state)
    sentences = re.split(r"(?<=[.!?])\s+", grounded)

    corrected = False
    kept: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue

        if not _ACTIVITY_CLAIM_VERB_PATTERN.search(sentence):
            kept.append(sentence)
            continue

        mentions = _extract_activity_mentions(sentence, active_cats)
        disallowed = sorted(cat for cat in mentions if cat not in allowed)

        named_entities = _extract_named_entity_claims(sentence, active_cats)
        unknown_entity_claim = bool(named_entities) and all(
            not _entity_matches_known_activity(entity, known_entities) for entity in named_entities
        )

        # Correct per-category quantity claims (e.g., "8 nightlife spots and 8 yoga sessions")
        # using authoritative activity tile counts.
        if (
            mentions
            and bool(re.search(r"\b\d+\b", sentence))
            and "day" not in sentence.lower()
            and "days" not in sentence.lower()
        ):
            authoritative = _build_authoritative_activity_category_sentence(
                mentions,
                category_counts,
            )
            if authoritative:
                corrected = True
                logger.debug(
                    "[VERIFY][SYNTH] corrected_activity_category_counts categories=%s",
                    sorted(mentions),
                )
                kept.append(authoritative)
                continue

        if disallowed or unknown_entity_claim:
            trimmed = _strip_additive_activity_fragment(sentence)
            corrected = True
            logger.debug(
                (
                    "[VERIFY][SYNTH] removed_unsupported_activity_claim "
                    "disallowed=%s unknown_entity=%s"
                ),
                disallowed,
                unknown_entity_claim,
            )
            if trimmed:
                if not re.search(r"[.!?]$", trimmed):
                    trimmed = f"{trimmed}."
                kept.append(trimmed)
            continue

        kept.append(sentence)

    merged = re.sub(r"\s+([,.;!?])", r"\1", " ".join(kept).strip())
    if corrected and not merged:
        return "Plan updated."
    return merged or grounded


def _strip_day_pref_recap_from_sentence(sentence: str) -> str:
    if not _DAY_PREF_RECAP_PATTERN.search(sentence or ""):
        return (sentence or "").strip()

    lowered = sentence.lower()
    first_match = _DAY_PREF_RECAP_PATTERN.search(sentence)
    assert first_match is not None

    cut_tokens = (
        ", allowing",
        ", with",
        ", including",
        ", featuring",
        " allowing more time to enjoy ",
        " with ",
        " including ",
        " featuring ",
        " now includes ",
        " now include ",
    )
    cut_points = []
    for token in cut_tokens:
        idx = lowered.find(token)
        if idx != -1 and idx <= first_match.start():
            cut_points.append(idx)

    if cut_points:
        stripped = sentence[: min(cut_points)].rstrip(" ,;:-")
    else:
        stripped = _DAY_PREF_RECAP_PATTERN.sub("", sentence)
        stripped = re.sub(
            r"\b(and|with|including|featuring)\b\s*(?=[,.;!?]|$)",
            "",
            stripped,
            flags=re.I,
        )
        stripped = re.sub(r"\s{2,}", " ", stripped).strip(" ,;:-")

    stripped = re.sub(
        r"(?:allowing more time to enjoy|to enjoy)\s*$",
        "",
        stripped,
        flags=re.IGNORECASE,
    ).strip(" ,;:-")

    if stripped and not re.search(r"[.!?]$", stripped):
        stripped = f"{stripped}."

    return stripped


def _ground_specialist_update_response(message: str, response_type: str) -> str:
    if response_type != "specialist_update":
        return message

    grounded = (message or "").strip()
    if not grounded:
        return grounded

    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", grounded) if s.strip()]
    cleaned: list[str] = []
    for sentence in sentences:
        updated = _strip_day_pref_recap_from_sentence(sentence)
        if updated != sentence:
            logger.debug("[VERIFY][SYNTH] stripped_day_preference_recap_from_specialist_update")
        if updated:
            cleaned.append(updated)

    if len(cleaned) > 2:
        cleaned = cleaned[:2]

    return " ".join(cleaned).strip() or grounded


def _strip_tile_count_claim_sentences(message: str) -> tuple[str, set[str]]:
    sentences = re.split(r"(?<=[.!?])\s+", (message or "").strip())
    kept: list[str] = []
    claimed_categories: set[str] = set()

    for sentence in sentences:
        claimed = _extract_claimed_tile_categories(sentence)
        if claimed:
            claimed_categories |= claimed
            continue
        kept.append(sentence)

    return " ".join(kept).strip(), claimed_categories


def _build_authoritative_tile_count_sentence(state: GraphState, categories: set[str]) -> str:
    singular_labels = {"flights": "flight", "hotels": "hotel", "activities": "activity"}
    plural_labels = {"flights": "flights", "hotels": "hotels", "activities": "activities"}
    activity_tiles = state.tiles.get("activities", []) if state.tiles else []
    flight_tiles = state.tiles.get("flights", []) if state.tiles else []
    hotel_tiles = state.tiles.get("hotels", []) if state.tiles else []
    counts = {
        "flights": len([t for t in flight_tiles if t]),
        "hotels": len([t for t in hotel_tiles if t]),
        "activities": len([t for t in activity_tiles if t]),
    }

    order = ("hotels", "flights", "activities")
    parts = []
    for category in order:
        if category not in categories:
            continue
        count = counts[category]
        if count <= 0:
            continue
        label = singular_labels[category] if count == 1 else plural_labels[category]
        parts.append(f"**{count} {label}**")

    if not parts:
        return ""
    if len(parts) == 1:
        return f"Found {parts[0]}."
    if len(parts) == 2:
        return f"Found {parts[0]} and {parts[1]}."
    return f"Found {parts[0]}, {parts[1]}, and {parts[2]}."


def _strip_hallucinated_flight_count_claims(message: str) -> str:
    """Backward-compatible helper: strip only flight count/claim sentences."""
    sentences = re.split(r"(?<=[.!?])\s+", (message or "").strip())
    kept: list[str] = []
    for sentence in sentences:
        claimed = _extract_claimed_tile_categories(sentence)
        if "flights" in claimed:
            continue
        kept.append(sentence)
    return " ".join(kept).strip()


def _ground_flight_response(message: str, state: GraphState) -> str:
    """
    Ensure chat text doesn't claim flights that were not actually returned.
    """
    grounded, claimed_categories = _strip_tile_count_claim_sentences(message)
    if claimed_categories:
        authoritative_counts = _build_authoritative_tile_count_sentence(state, claimed_categories)
        if authoritative_counts:
            grounded = (
                f"{grounded} {authoritative_counts}".strip() if grounded else authoritative_counts
            )
        logger.debug(
            "[VERIFY][SYNTH] corrected_tile_count_claims categories=%s",
            sorted(claimed_categories),
        )

    grounded = _ground_activity_claims(grounded, state)

    flights_found = len([t for t in state.tiles.get("flights", []) if t]) if state.tiles else 0
    if flights_found <= 0:
        stripped = _strip_hallucinated_flight_count_claims(grounded)
        if stripped != grounded:
            grounded = stripped
            logger.debug("[VERIFY][SYNTH] removed_hallucinated_flight_claim")

    settings = get_trip_settings(state)
    flights_requested = settings.booking_types.flights != "off"
    skip_reason = state.metadata.get("flight_skip_reason")
    status = state.metadata.get("flight_search_status")
    needs_origin = skip_reason == "no_origin_for_flights" or status == "skipped_no_origin"

    if flights_requested and needs_origin:
        lowered = grounded.lower()
        if "departure city" not in lowered and "origin" not in lowered:
            prompt = "Share your departure city to see flight options."
            grounded = f"{grounded} {prompt}".strip() if grounded else prompt
            logger.debug("[VERIFY][SYNTH] added_origin_prompt_for_flights")

    return grounded or message


async def synthesize_with_llm(
    state: GraphState,
    response_type: str | None = None,
) -> tuple[str | None, dict]:
    """
    Generate response using LLM for coherent synthesis.

    Weaves together Architect, Specialist, and Guard outputs
    into a single, natural-sounding response.

    Args:
        state: Current graph state
        response_type: Response type for model selection (auto-detected if None)

    Returns tuple of (response_content, token_usage_dict).
    """
    # Template bypass for known violations — skips LLM entirely (~786ms saved).
    # Returns {"template_bypass": True} so caller can correctly set used_llm=False.
    templated = _try_template_response(state)
    if templated is not None:
        logger.info("[SYNTH] Template bypass — skipping LLM for known violation")
        return templated, {"template_bypass": True}

    # Auto-detect response type if not provided
    if response_type is None:
        response_type = _get_response_type(state)

    # Get model for this response type
    llm = _get_synthesizer_llm(response_type)

    system_prompt = _load_system_prompt(state)  # GAP 2: Pass state for Jinja2 rendering
    context = _build_synthesis_context(state, response_type)  # Pass response_type for 8C

    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=f"Synthesize a response for this context:\n\n{context}"),
    ]

    try:
        # Log model selection for debugging
        logger.debug(f"Using model={_get_model_id(llm)} for response_type={response_type}")

        # Use non-streaming for the node (streaming handled by astream_events)
        response = await llm.ainvoke(messages)
        token_usage = extract_token_usage(response, model=_get_model_id(llm))
        # Extract content — handles string (OpenAI) and list-of-parts (Gemini)
        content = extract_json_content(response)

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

# Single fallback for when LLM synthesis fails (reachable in production if OpenAI returns None)
FALLBACK_MESSAGE = (
    "I've updated your trip plan — check the itinerary on the right. "
    "Let me know if you'd like to adjust anything."
)


# =============================================================================
# Templated Responses for Known Constraint Violations
# =============================================================================

# ── Builders ──────────────────────────────────────────────────────────────────


def _template_day_preference_exceeds(v: dict, state: GraphState) -> str:
    """DAY_PREFERENCE_EXCEEDS_CAPACITY — most common violation."""
    settings = get_trip_settings(state)
    day_prefs = settings.activity_settings.day_preferences or {}

    # INFO-1 fix: guard empty day_prefs
    if not day_prefs:
        return "The planned activities need more days than available. Consider extending your trip."

    cat_parts = []
    for cat, days in day_prefs.items():
        cat_parts.append(f"**{days} day{'s' if days != 1 else ''}** of {cat}")

    if len(cat_parts) == 1:
        activity_phrase = cat_parts[0]
    elif len(cat_parts) == 2:
        activity_phrase = f"{cat_parts[0]} and {cat_parts[1]}"
    else:
        activity_phrase = ", ".join(cat_parts[:-1]) + f", and {cat_parts[-1]}"

    return (
        f"the plan includes {activity_phrase}, but you'll need an extra day "
        f"to allow for a safe buffer between activities. "
        f"Extending your trip by a day or reducing one activity would resolve this."
    )


# WARNING-1: TRIP_TOO_SHORT has severity="warning" in constraint_guard.py,
# so it never reaches the blocking filter in _try_template_response.
# Omitted from registry. If guard severity is upgraded to blocking, add it here.


def _template_date_order(v: dict, state: GraphState) -> str:
    """DATE_ORDER_INVALID — standalone, no dest/date prefix (BLOCKING-2)."""
    return "It looks like the end date is before the start date. Could you double-check your dates?"


def _template_same_city(v: dict, state: GraphState) -> str:
    """SAME_CITY_ERROR — standalone, no dest/date prefix (BLOCKING-2)."""
    return "Your departure city and destination are the same. Where are you traveling from?"


def _template_unknown_destination(v: dict, state: GraphState) -> str:
    """UNKNOWN_DESTINATION_ERROR — standalone, no dest/date prefix (BLOCKING-2).

    BLOCKING-1 fix: read invalid dest from violation message, not live state.
    Guard rolls back state.trip_plan.destination before synthesizer runs.
    """
    msg = v.get("message", "That destination could not be verified.")
    return f"{msg} Could you check the spelling or try a different destination?"


# ── Registry ──────────────────────────────────────────────────────────────────
# Add new codes here. Never touch dispatch logic in _try_template_response.

_VIOLATION_TEMPLATES: dict[str, Callable[[dict, GraphState], str]] = {
    "DAY_PREFERENCE_EXCEEDS_CAPACITY": _template_day_preference_exceeds,
    # TRIP_TOO_SHORT omitted — severity="warning", never reaches blocking filter
    "DATE_ORDER_INVALID": _template_date_order,
    "SAME_CITY_ERROR": _template_same_city,
    "UNKNOWN_DESTINATION_ERROR": _template_unknown_destination,
}

# Route-category codes that render standalone (no "For **dest**..." prefix).
_ROUTE_CODES = {"SAME_CITY_ERROR", "UNKNOWN_DESTINATION_ERROR", "DATE_ORDER_INVALID"}


def _try_template_response(state: GraphState) -> str | None:
    """
    Attempt deterministic response for known violation patterns.

    Returns complete response string if every blocking violation is templateable,
    or None to fall through to LLM synthesis.

    Dispatch on GuardViolation.code (enumerated). No regex, no string parsing.
    """
    violations = state.metadata.get("constraint_violations", [])
    blocking = [v for v in violations if v.get("severity") == "blocking"]

    if not blocking:
        return None

    # Only bypass when ALL blocking violations have a template.
    # Mixed known + unknown → LLM handles the nuance.
    if not all(v.get("code") in _VIOLATION_TEMPLATES for v in blocking):
        return None

    parts = []
    for v in blocking:
        builder = _VIOLATION_TEMPLATES[v["code"]]
        fragment = builder(v, state)
        if fragment:
            parts.append(fragment)

    if not parts:
        return None

    # BLOCKING-2 fix: route/temporal violations render standalone — no dest/date prefix.
    # Planning violations (capacity) get the "For **dest**..." prefix.
    all_route = all(v.get("code") in _ROUTE_CODES for v in blocking)

    if all_route:
        # BLOCKING-4 fix: join with double newline; each builder returns a complete sentence.
        return "\n\n".join(parts)

    # Prefixed path for planning violations (e.g. DAY_PREFERENCE_EXCEEDS_CAPACITY)
    plan = state.trip_plan
    dest = plan.destination or "your destination"

    # BLOCKING-3 fix: use f"{s.day}" — %-d is Linux/macOS-only and raises on Windows.
    dates = ""
    if plan.start_date and plan.end_date:
        from datetime import datetime

        try:
            s = datetime.strptime(plan.start_date, "%Y-%m-%d")
            e = datetime.strptime(plan.end_date, "%Y-%m-%d")
            dates = f" from **{s.strftime('%B')} {s.day}** to **{e.strftime('%B')} {e.day}**"
        except ValueError:
            pass

    # Each planning-violation fragment starts lowercase to flow after the prefix comma.
    violation_text = "\n\n".join(parts)

    tile_sentence = _build_authoritative_tile_count_sentence(
        state, {"hotels", "flights", "activities"}
    )

    message = f"For **{dest}**{dates}, {violation_text}"
    if tile_sentence:
        message = f"{message} {tile_sentence}"

    return message


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
    constraint_violations = state.metadata.get("constraint_violations", [])

    # ── Step 0: Budget blocking violations (budget-specific chips) ──
    budget_blocking = [
        v
        for v in constraint_violations
        if v.get("severity") == "blocking" and v.get("category") == "budget"
    ]
    if budget_blocking:
        chips = []
        plan = state.trip_plan

        # "Increase budget to $X" — suggest 120% of current total cost rounded to nearest 100
        total_cost = 0.0
        for cat_tiles in (state.tiles or {}).values():
            if not isinstance(cat_tiles, list):
                continue
            for t in cat_tiles:
                if isinstance(t, dict):
                    total_cost += t.get("price_estimate") or t.get("live_price") or 0
        if plan.budget and total_cost > plan.budget:
            suggested_budget = int(total_cost * 1.2 / 100) * 100
            chips.append(f"Increase budget to ${suggested_budget:,}")

        # "Find cheaper {largest_cat}" — target the largest overspent category
        category_costs: dict[str, float] = {}
        for cat, cat_tiles in (state.tiles or {}).items():
            if not isinstance(cat_tiles, list):
                continue
            cat_total = sum(
                t.get("price_estimate") or t.get("live_price") or 0
                for t in cat_tiles
                if isinstance(t, dict)
            )
            if cat_total > 0:
                category_costs[cat] = cat_total
        if category_costs:
            largest_cat = max(category_costs, key=category_costs.get)
            chips.append(f"Find cheaper {largest_cat}")

        # "Fewer activity days" — if activities exist
        if state.tiles.get("activities"):
            chips.append("Fewer activity days")

        result = chips[:3]
        state.metadata["suggestion_chip_meta"] = [
            {"chip_type": "cta", "category": "budget_fix", "icon": "dollar-sign"}
        ] * len(result)
        state.metadata["suggestion_chips"] = [
            {
                "message": text,
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "cta",
                "category": "budget_fix",
                "icon": "dollar-sign",
            }
            for text in result
        ]
        return result

    # ── Step 1: Blocking violations (highest priority) ──
    blocking = [
        v
        for v in constraint_violations
        if v.get("severity") == "blocking" and v.get("category") not in ("route", "budget")
    ]
    if blocking:
        chips = []
        plan = state.trip_plan

        # "Extend to Feb 24" — concrete date the router can parse
        # Use builder's new_duration if available (more accurate than +2 heuristic)
        if plan.end_date:
            from datetime import datetime, timedelta

            end = datetime.strptime(plan.end_date, "%Y-%m-%d")
            builder_resolutions = state.metadata.get("last_builder_resolutions", [])
            extend_res = next(
                (r for r in builder_resolutions if r.get("action") == "extend_trip"), None
            )
            if extend_res and extend_res.get("new_duration") and plan.start_date:
                start = datetime.strptime(plan.start_date, "%Y-%m-%d")
                extended = start + timedelta(days=extend_res["new_duration"] - 1)
            else:
                extended = end + timedelta(days=2)
            chips.append(f"Extend to {extended.strftime('%b %-d')}")

        # "Add buffer day between activities" — restructure without extending
        chips.append("Add buffer day between activities")

        # "Remove hiking" — from violation's conflicting specialists
        settings = get_trip_settings(state)
        active_cats = set(settings.activity_settings.categories)
        for v in blocking:
            for cat in sorted(v.get("conflicting_specialists", [])):
                if cat in active_cats:
                    chip = f"Remove {cat}"
                    if chip not in chips:
                        chips.append(chip)

        # "Reduce diving to 2 days" — for day preference capacity violations
        day_prefs = settings.activity_settings.day_preferences
        for v in blocking:
            if v.get("code") == "DAY_PREFERENCE_EXCEEDS_CAPACITY" and day_prefs:
                largest = max(day_prefs, key=day_prefs.get)
                reduced = day_prefs[largest] - 1
                if reduced > 0:
                    chip = f"Reduce {largest} to {reduced} days"
                    if chip not in chips:
                        chips.append(chip)

        result = chips[:3] if chips else [blocking[0].get("suggested_action", "Adjust your dates")]
        state.metadata["suggestion_chip_meta"] = [
            {"chip_type": "cta", "category": "blocking_fix", "icon": "alert-triangle"}
        ] * len(result)
        state.metadata["suggestion_chips"] = [
            {
                "message": text,
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "cta",
                "category": "blocking_fix",
                "icon": "alert-triangle",
            }
            for text in result
        ]
        return result

    # ── Step 2: Route violations ──
    route_violations = [v for v in constraint_violations if v.get("category") == "route"]
    if route_violations:
        prev_dest = state.trip_plan.destination
        if prev_dest:
            result = [f"Back to {prev_dest}", "Different city", "Help me choose"]
        else:
            result = ["Explore somewhere new", "Help me choose", "Show me options"]
        state.metadata["suggestion_chip_meta"] = [
            {"chip_type": "cta", "category": "route_fix", "icon": "map-pin"}
        ] * len(result)
        state.metadata["suggestion_chips"] = [
            {
                "message": text,
                "action_type": "send_message",
                "action_target": None,
                "chip_type": "cta",
                "category": "route_fix",
                "icon": "map-pin",
            }
            for text in result
        ]
        return result

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

    # ── Step 6: Render templates + collect chip metadata ──
    CTA_CATEGORIES = {"destination_choice", "date_prompt", "date_contextual"}
    SETTING_CATEGORIES = {"plan_hotel_pref", "plan_flight_pref", "plan_budget"}

    def _render_suggestion_text(candidate: dict, month_text: str) -> str:
        text = candidate["template"]
        text = text.replace("{destination}", dest)
        text = text.replace("{month}", month_text)
        return text

    def _suggestion_text_key(text: str) -> str:
        return re.sub(r"\s+", " ", (text or "").strip().lower())

    month = state.metadata.get("detected_month", "")
    previous_text_keys = {
        _suggestion_text_key(text)
        for text in state.metadata.get("last_suggested_replies", [])
        if isinstance(text, str) and text.strip()
    }
    candidate_queue: list[dict] = list(final)
    seen_candidate_ids = {id(c) for c in candidate_queue}
    # Always append alternates so prior-turn chips can rotate out even when
    # the first-pass queue is already length 3.
    for candidate in sorted(eligible, key=lambda c: c["priority"]):
        cid = id(candidate)
        if cid in seen_candidate_ids:
            continue
        candidate_queue.append(candidate)
        seen_candidate_ids.add(cid)

    result: list[str] = []
    meta_list: list[dict] = []
    structured_chips: list[dict] = []
    unique_candidates: list[dict] = []
    seen_text_keys: set[str] = set()

    def _append_candidate(c: dict, *, allow_previous: bool) -> bool:
        if len(result) >= 3:
            return False
        text = _render_suggestion_text(c, month)
        text_key = _suggestion_text_key(text)
        if text_key in seen_text_keys:
            logger.debug(f"[SUGGESTIONS] deduped duplicate chip='{text}'")
            return False
        if not allow_previous and text_key in previous_text_keys:
            logger.debug(f"[SUGGESTIONS] rotated previous-turn chip='{text}'")
            return False
        seen_text_keys.add(text_key)

        cat = c.get("category", "")
        if cat in CTA_CATEGORIES or c.get("priority", 10) <= 1:
            chip_type = "cta"
        elif cat in SETTING_CATEGORIES:
            chip_type = "setting"
        else:
            chip_type = "follow_up"

        # Candidate-level icon override takes precedence over category default
        icon = c.get("icon")
        if icon is None:
            if cat.startswith("specialist_"):
                icon = "compass"
            elif cat.startswith("plan_"):
                icon = "sliders-horizontal"
            elif cat.startswith("question_"):
                icon = "help-circle"
            elif cat in {"date_prompt", "date_contextual"}:
                icon = "calendar"

        meta = {"chip_type": chip_type, "category": cat, "icon": icon}
        action_type, action_target = PILL_ACTION_MAP.get(cat, ("send_message", None))

        result.append(text)
        meta_list.append(meta)
        unique_candidates.append(c)
        structured_chips.append(
            {
                "message": text,
                "action_type": action_type,
                "action_target": action_target,
                "chip_type": chip_type,
                "category": cat,
                "icon": icon,
            }
        )
        return True

    # Pass 1: prefer never-shown-in-previous-turn chips.
    for c in candidate_queue:
        if len(result) >= 3:
            break
        _append_candidate(c, allow_previous=False)

    # Pass 2: if we still need slots, allow repeats from previous turn.
    if len(result) < 3:
        for c in candidate_queue:
            if len(result) >= 3:
                break
            _append_candidate(c, allow_previous=True)

    state.metadata["suggestion_chip_meta"] = meta_list
    state.metadata["suggestion_chips"] = structured_chips
    state.metadata["last_suggested_replies"] = result

    # ── Step 7: Track shown question types for rotation ──
    shown_qtypes = [
        c["category"].replace("question_", "")
        for c in unique_candidates
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
        self.debug = settings.debug_plan_messages

    def synthesize_greeting(self, _state: GraphState) -> str:
        """Generate greeting response."""
        return GREETING_TEMPLATE

    def synthesize_inspiration(self, _state: GraphState) -> str:
        """Generate inspiration (pre-core) response."""
        return FALLBACK_MESSAGE

    def synthesize_planning(self, _state: GraphState) -> str:
        """Generate planning response."""
        return FALLBACK_MESSAGE

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
    import time

    from app.debug_utils import CompactLogger, _debug_node_end, _debug_node_start

    node_start_time = time.time()
    metrics = state.metadata.get("_metrics")
    clog = CompactLogger("synthesizer", metrics=metrics)

    _debug_node_start(
        "synthesizer",
        "📝",
        mode=state.metadata.get("architect_mode"),
        has_tiles=bool(state.tiles),
        has_specialist=bool(
            state.active_specialist or state.metadata.get("last_executed_specialist")
        ),
    )
    clog.node_start(
        "SYNTHESIZER",
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
        duration_ms = int((time.time() - node_start_time) * 1000)
        clog.node_end("SYNTHESIZER", duration_ms, speculative=True, message_len=0)
        return state

    synth = Synthesizer()

    # Start image fetch in parallel with LLM synthesis (latency masking)
    image_task = asyncio.create_task(enrich_with_images(state))

    # Determine routing preference for LLM vs template paths.
    # Observability uses runtime flags below to reflect actual calls.
    llm_route_enabled = _should_use_llm_synthesis(state)
    llm_attempted = False
    llm_called = False
    message = ""
    response_type = _get_response_type(state)

    from app.debug_utils import log, log_tokens

    try:
        # Settings update gate — check if new content was generated
        # Terse ack OK for pure settings changes (e.g., "4-star hotels only")
        # Full LLM synthesis needed when tiles/categories generated, violations,
        # or structural changes (date shifts) that require natural-language framing
        turn_applied_fields = state.metadata.get("turn_applied_fields", [])
        has_violations = len(state.metadata.get("constraint_violations", [])) > 0
        has_date_change = any(f in turn_applied_fields for f in ("start_date", "end_date"))
        has_new_content = bool(
            state.metadata.get("tier2_new_content_generated")  # NEW Tier 2 content this turn
            or len(state.metadata.get("added_categories", [])) > 0  # NEW categories added
            or has_date_change  # Date shift needs LLM framing, not terse ack
        )

        if (
            state.metadata.get("settings_just_updated")
            and not has_violations
            and not has_new_content
        ):
            # Only use terse ack for pure settings changes
            message = state.metadata.get("actionable_acknowledgment", "") or state.last_summary
            log("SYNTH", "Settings update (terse ack OK, no new content)")
        elif state.metadata.get("settings_just_updated") and (has_violations or has_new_content):
            # Violations override settings shortcut — use full LLM response
            if has_violations:
                log("SYNTH", "Settings update has violations — routing to LLM")
            else:
                log("SYNTH", "Settings update generated new content — routing to LLM")
            llm_attempted = True
            llm_response, token_usage = await synthesize_with_llm(state, response_type)
            # WARNING-2 fix: template bypass returns {"template_bypass": True}; don't
            # count it as an LLM call in observability metadata.
            llm_called = not token_usage.get("template_bypass", False)
            if llm_response:
                message = llm_response
                if token_usage and not token_usage.get("template_bypass"):
                    model_used = token_usage.get("model", "unknown")
                    prompt_tokens = token_usage.get("prompt_tokens", 0)
                    completion_tokens = token_usage.get("completion_tokens", 0)
                    log_tokens(
                        "SYNTH",
                        prompt_tokens,
                        completion_tokens,
                        token_usage.get("total_tokens", 0),
                    )
                    clog.llm_call(
                        model=model_used,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        purpose=response_type,
                    )
                    log("SYNTH", f"Model: {model_used}, Response type: {response_type}")
            else:
                output = synth.generate_response(state)
                message = output.message
                log("SYNTH", "Using template (LLM failed for violation response)")
        elif llm_route_enabled:
            # Use LLM for complex planning responses
            logger.debug("Using LLM synthesis for response generation")
            log("SYNTH", "Generating LLM response...")
            llm_attempted = True
            llm_response, token_usage = await synthesize_with_llm(state, response_type)
            # WARNING-2 fix: template bypass returns {"template_bypass": True}; don't
            # count it as an LLM call in observability metadata.
            llm_called = not token_usage.get("template_bypass", False)
            if llm_response:
                message = llm_response
                if token_usage and not token_usage.get("template_bypass"):
                    model_used = token_usage.get("model", "unknown")
                    prompt_tokens = token_usage.get("prompt_tokens", 0)
                    completion_tokens = token_usage.get("completion_tokens", 0)
                    log_tokens(
                        "SYNTH",
                        prompt_tokens,
                        completion_tokens,
                        token_usage.get("total_tokens", 0),
                    )
                    clog.llm_call(
                        model=model_used,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        purpose=response_type,
                    )
                    log("SYNTH", f"Model: {model_used}, Response type: {response_type}")
            else:
                # Fallback to template
                output = synth.generate_response(state)
                message = output.message
                # If gate-blocked and template produced nothing useful, use pre-computed fallback
                if state.metadata.get("short_circuit_type") == "gate_blocked" and len(message) < 20:
                    message = state.metadata.get(
                        "_gate_blocked_fallback",
                        "Something doesn't look right with those inputs -- could you double-check?",
                    )
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

    # Final grounding pass: avoid flight-count claims when logistics skipped flights.
    # Template-bypassed responses are grounded by construction (they read structured state
    # directly) — skip the hallucination stripper so it doesn't eat activity-name mentions.
    if llm_called:
        message = _ground_flight_response(message, state)
        message = _ground_specialist_update_response(message, response_type)

    # Generate suggestion chips (always template-based for consistency)
    # Always regenerate to ensure fresh suggestions on every turn
    suggested_replies = generate_suggestions(state)

    # Log response details
    _chips = state.metadata.get("suggestion_chips", [])
    _meta = state.metadata.get("suggestion_chip_meta", [])
    log(
        "SYNTH",
        f"Response: {len(message)} chars | "
        f"replies={len(suggested_replies)} chips={len(_chips)} meta={len(_meta)}",
    )
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
        "used_llm": llm_called,
        "llm_attempted": llm_attempted,
    }

    _debug_node_end(
        "synthesizer",
        "📝",
        response_len=len(message),
        suggested_replies=suggested_replies,
        used_llm=llm_called,
    )
    duration_ms = int((time.time() - node_start_time) * 1000)
    clog.node_end(
        "SYNTHESIZER",
        duration_ms,
        response_len=len(message),
        used_llm=llm_called,
        suggestions=len(suggested_replies),
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
        # Gate-blocked needs LLM to explain the issue naturally
        if state.metadata.get("short_circuit_type") == "gate_blocked":
            return True
        return False

    # Everything else uses LLM - even missing_fields, pre_core, etc.
    # The prompt controls the response style and content
    return True
