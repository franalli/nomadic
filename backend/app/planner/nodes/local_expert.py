"""
Local Expert Node - The "Logistics Concierge" for city trips.

This specialist activates by default when no niche specialist (diving/hiking/skiing)
is requested. It provides city-specific constraints and tips:
- Opening hours and closed days
- Booking lead times for popular attractions
- Transit passes and efficiency tips
- Cultural considerations (dining hours, tipping, dress codes)

Goal: Ensure the Agent Feed is never empty for generic trips.
"""

import os
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import settings
from app.data.demo_curation import DEMO_MANIFEST
from app.placeholders import get_destination_gallery
from app.planner.llm_factory import get_llm_by_model
from app.planner.nodes.expert_constraints import (
    LocalExpertOutput,
    LocalRecommendation,
    _get_static_local_knowledge,
)
from app.planner.services.section_builder import (
    build_local_expert_section,
    mark_topic_executed,
    upsert_section,
)
from app.planner.state import GraphState

# =============================================================================
# Local Expert Node
# =============================================================================


async def local_expert(state: GraphState) -> GraphState:
    """
    The 'Concierge' agent. Adds logistical constraints and city tips.

    Triggered by default when no niche specialist is requested.
    Returns a StrategySection with constraints and recommendations.

    CRITICAL: Multi-specialist support - same pattern as vertical_specialist.
    """
    from app.debug_utils import log

    # MULTI-SPECIALIST SUPPORT: Pop from pending if active_specialist is not set
    if not state.active_specialist and state.pending_specialists:
        next_specialist = state.pending_specialists[0]
        state.pending_specialists = state.pending_specialists[1:]
        state.active_specialist = next_specialist
        state.active_agent_id = next_specialist
        state.ui_events.append("SPECIALIST_ACTIVE")
        log("LOCAL_EXPERT", f"Multi-specialist loop: popped '{next_specialist}' from queue")
        # If next specialist is not local_expert, we shouldn't be here - but handle gracefully
        if next_specialist != "local_expert":
            log("LOCAL_EXPERT", f"WARNING: Expected local_expert but got {next_specialist}")

    plan = state.trip_plan

    # Skip if no destination
    if not plan.destination:
        log("LOCAL_EXPERT", "Skipped - no destination set")
        state.metadata["last_executed_specialist"] = "local_expert"  # Track for downstream
        state.active_specialist = None  # Clear for multi-specialist support
        return state

    log("LOCAL_EXPERT", f"Activated for {plan.destination}")

    # ==========================================================================
    # SELECTIVE REGENERATION: Check if cached output can be reused
    # @see docs/plan_graph_analysis.md - Selective Regeneration Strategy
    # ==========================================================================
    existing_sections = state.metadata.get("strategy_sections", [])
    cached_section = next(
        (s for s in existing_sections if s.get("specialist_type") == "local_expert"), None
    )

    if cached_section:
        # Check if destination matches (local_expert caches are destination-specific)
        # The title format is "{destination} Trip Overview"
        cached_title = cached_section.get("title", "")
        current_destination = plan.destination
        if cached_title and current_destination and current_destination in cached_title:
            log("LOCAL_EXPERT", f"Cache HIT: Reusing cached output for {current_destination}")
            state.metadata["last_executed_specialist"] = "local_expert"
            state.active_specialist = None
            return state  # No-op, output already in state from session restore

    try:
        return await _run_local_expert(state, plan, log)
    except Exception as e:
        # Catch any unexpected errors to prevent graph crash
        from app.debug_utils import _debug_error

        _debug_error(f"LOCAL_EXPERT unexpected error: {e}")
        log("LOCAL_EXPERT", f"Error - returning state unchanged: {type(e).__name__}")
        state.metadata["last_executed_specialist"] = "local_expert"  # Track for downstream
        state.active_specialist = None  # Clear for multi-specialist support
        return state


async def _run_local_expert(state: GraphState, plan, log) -> GraphState:
    """Inner implementation with the actual logic."""

    # ==========================================================================
    # Step 1: Get static knowledge first (guaranteed content)
    # ==========================================================================
    static_knowledge = _get_static_local_knowledge(plan.destination)
    has_static = bool(static_knowledge.constraints)

    if has_static:
        log("LOCAL_EXPERT", f"Found static knowledge for {plan.destination}")

    # ==========================================================================
    # Step 2: Try LLM for additional/dynamic content
    # ==========================================================================
    response = None
    use_llm = os.getenv("LOCAL_EXPERT_USE_LLM", "false").lower() == "true"

    if use_llm:
        prompts_dir = Path(__file__).parent.parent.parent / "prompts" / "specialists"
        prompt_file = prompts_dir / "local_expert.txt"

        if prompt_file.exists():
            system_prompt = prompt_file.read_text()
        else:
            system_prompt = """You are a local logistics expert. Provide:
1. Constraints: Opening hours, booking requirements, seasonal considerations
2. Recommendations: Transit passes, efficiency tips, cultural notes
Output as JSON with "constraints" and "recommendations" arrays."""

        user_context = f"""
Destination: {plan.destination}
Dates: {plan.start_date or "Not specified"} to {plan.end_date or "Not specified"}
Travelers: {plan.adults} adults{f", {plan.children} children" if plan.children else ""}
"""

        llm = get_llm_by_model(
            settings.extraction_model, temperature=0.3, timeout=30, max_retries=1
        )
        structured_llm = llm.with_structured_output(LocalExpertOutput)

        log("LOCAL_EXPERT", f"Calling LLM ({settings.extraction_model})...")

        try:
            response = await structured_llm.ainvoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_context),
                ]
            )
            log("LOCAL_EXPERT", "LLM call completed")
        except Exception as e:
            from app.debug_utils import _debug_error

            _debug_error(f"LOCAL_EXPERT LLM Error: {e}")
            log("LOCAL_EXPERT", f"LLM error, using static knowledge: {type(e).__name__}")
            response = None
    else:
        log("LOCAL_EXPERT", "Using static knowledge only (LLM disabled)")

    # ==========================================================================
    # Step 3: Merge static and LLM content (prefer static for consistency)
    # ==========================================================================
    if response is None:
        response = static_knowledge
    elif has_static:
        # Merge: static constraints first, then LLM additions
        merged_constraints = list(static_knowledge.constraints)

        # Add LLM constraints that don't duplicate static
        static_constraint_descs = {c.description for c in static_knowledge.constraints}

        for c in response.constraints:
            if c.description not in static_constraint_descs:
                merged_constraints.append(c)

        response = LocalExpertOutput(
            constraints=merged_constraints[:5],  # Limit to prevent clutter
            recommendations=response.recommendations[:5],  # LLM recommendations only
        )

    # CRITICAL: Always generate a Trip Overview, even without specific knowledge
    # This ensures the UI has an anchor card (Trip DNA) for the destination
    # @see docs/ux_unified_architecture.md Section III.A - "Local Expert Always First"
    if not response.constraints and not response.recommendations:
        log(
            "LOCAL_EXPERT",
            f"No specific knowledge for {plan.destination} - generating Trip Overview",
        )
        # Generate basic Trip Overview with Unsplash images
        response = LocalExpertOutput(
            constraints=[],
            recommendations=[
                LocalRecommendation(
                    title=f"Explore {plan.destination}",
                    description=f"Discover the highlights of {plan.destination}",
                    category="general",
                    logic_hook="Destination Overview",
                ),
            ],
        )

    # ==========================================================================
    # Build Strategy Section
    # ==========================================================================

    # Map constraints to schema format
    constraints_applied = []
    for c in response.constraints:
        constraints_applied.append(
            {
                "rule": c.description,
                "type": c.type,
                "severity": c.severity,
                "reason": c.description,
            }
        )

    # Map recommendations to content_added format
    content_added = []
    for r in response.recommendations:
        content_added.append(
            {
                "title": r.title,
                "description": r.description,
                "type": r.category,
                "logic_hook": r.logic_hook,
            }
        )

    # Fetch destination gallery ("Vibe Trio") if available
    dest_key = plan.destination.lower().strip()
    gallery_images = []
    if dest_key in DEMO_MANIFEST:
        gallery_images = DEMO_MANIFEST[dest_key].get("destination_gallery", [])

    # FALLBACK: Generate curated images for destinations without curated gallery
    # This ensures the Magazine Layout always has visual content
    if not gallery_images:
        gallery_images = get_destination_gallery(plan.destination)

    # Build comprehensive travel intelligence data from 12 categories
    travel_intelligence = {
        "destination_overview": (
            response.destination_overview.model_dump() if response.destination_overview else None
        ),
        "visa_entry": response.visa_entry.model_dump() if response.visa_entry else None,
        "safety_health": response.safety_health.model_dump() if response.safety_health else None,
        "money_costs": response.money_costs.model_dump() if response.money_costs else None,
        "transportation": response.transportation.model_dump() if response.transportation else None,
        "cultural_norms": response.cultural_norms.model_dump() if response.cultural_norms else None,
        "connectivity": response.connectivity.model_dump() if response.connectivity else None,
        "seasonality": response.seasonality.model_dump() if response.seasonality else None,
        "things_to_do": response.things_to_do.model_dump() if response.things_to_do else None,
        "neighborhoods": response.neighborhoods.model_dump() if response.neighborhoods else None,
        "accommodation": response.accommodation.model_dump() if response.accommodation else None,
        "scams_traps": response.scams_traps.model_dump() if response.scams_traps else None,
        "packing": response.packing.model_dump() if response.packing else None,
        "quick_tips": response.quick_tips or [],
    }

    # Build the strategy section
    # NOTE: Local Expert uses Magazine Layout (gallery + tips), NOT General Layout (stats grid)
    # trip_summary is intentionally OMITTED - frontend renders different layout for local_expert
    # @see docs/ux_unified_architecture.md Section XII - Magazine Layout for Local Expert
    one_liner = (
        response.destination_overview.tagline
        if response.destination_overview and response.destination_overview.tagline
        else f"Your adventure in {plan.destination}"
    )
    section = build_local_expert_section(
        destination=plan.destination,
        one_liner=one_liner,
        bullets=[c.description for c in response.constraints[:3]],
        must_dos=[r.title for r in response.recommendations[:5]],
        logistics_notes=[r.description for r in response.recommendations],
        constraints_applied=constraints_applied,
        content_added=content_added,
        gallery_images=gallery_images,
        travel_intelligence=travel_intelligence,
    )

    # ==========================================================================
    # Update State
    # ==========================================================================

    # DEBUG: Log incoming strategy_sections
    from app.debug_utils import _debug_log

    incoming_sections = state.metadata.get("strategy_sections", [])
    _debug_log(
        f"local_expert: BEFORE update - {len(incoming_sections)} sections, "
        f"types={[s.get('specialist_type') for s in incoming_sections]}"
    )

    upsert_section(state.metadata, section, mode="appendable")

    # DEBUG: Log outgoing strategy_sections
    outgoing_sections = state.metadata.get("strategy_sections", [])
    _debug_log(
        f"local_expert: AFTER update - {len(outgoing_sections)} sections, "
        f"types={[s.get('specialist_type') for s in outgoing_sections]}"
    )

    mark_topic_executed(state.metadata, "local_expert")

    log(
        "LOCAL_EXPERT",
        f"Added {len(constraints_applied)} constraints, {len(content_added)} tips",
    )

    state.metadata["local_expert_ran"] = True  # Persistent flag to prevent double execution
    state.metadata["last_executed_specialist"] = "local_expert"  # Track for downstream
    state.active_specialist = None  # Clear for multi-specialist support
    return state
