"""
Local Expert Node - The "Logistics Concierge" for city trips.

This specialist activates by default when no niche specialist (diving/hiking/skiing)
is requested. It provides city-specific constraints and tips:
- Opening hours and closed days
- Booking lead times for popular attractions
- Transit passes and efficiency tips
- Cultural considerations (dining hours, tipping, dress codes)

Goal: Ensure the Agent Feed is never empty for generic trips.

Architecture — Tier 1 Decouple (skeleton-first):
  Phase A: Instant skeleton from static constraint data (0ms, no LLM).
  Phase B: Background LLM enrichment written to DB after graph completes.
"""

import asyncio
import json
import logging
import time
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.config import settings
from app.data.demo_curation import DEMO_MANIFEST
from app.placeholders import get_destination_gallery
from app.planner.llm_factory import extract_json_content, extract_token_usage, get_llm_by_model
from app.planner.nodes.expert_constraints import (
    LocalExpertOutput,
    _get_constraint_context,
    _get_constraints_as_list,
)
from app.planner.services.section_builder import (
    build_local_expert_section,
    mark_topic_executed,
    upsert_section,
)
from app.planner.state import GraphState
from app.planner.state.typed_meta import get_trip_settings

logger = logging.getLogger(__name__)

# Cache schema JSON at module load — generated once, reused on every call (~18KB, ~7K tokens)
_LOCAL_EXPERT_SCHEMA_JSON: str = json.dumps(LocalExpertOutput.model_json_schema(), indent=2)

# Module-level registry for pending Phase B enrichment coroutine-factories.
# Keyed by session_id so streaming.py can retrieve and fire them after db.commit().
# Function references cannot survive JSON serialization through state_to_session_state,
# so they must live here rather than in state.metadata.
_MAX_PENDING_ENRICHMENTS = 50
_ENRICHMENT_TTL_SECONDS = 120  # 2 minutes
_pending_enrichments: dict[str, tuple[object, float]] = {}  # (factory, monotonic_ts)
_pending_lock = asyncio.Lock()  # Protects _pending_enrichments against coroutine interleaving

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
    except asyncio.CancelledError:
        raise  # Propagate cooperative cancellation — never swallow
    except Exception as e:
        # Catch any unexpected errors to prevent graph crash
        from app.debug_utils import _debug_error

        _debug_error(f"LOCAL_EXPERT unexpected error: {e}")
        log("LOCAL_EXPERT", f"Error - returning state unchanged: {type(e).__name__}")
        state.metadata["last_executed_specialist"] = "local_expert"  # Track for downstream
        state.active_specialist = None  # Clear for multi-specialist support
        return state


async def _run_local_expert(state: GraphState, plan, log) -> GraphState:
    """Inner implementation — skeleton-first, background LLM enrichment."""

    # ==========================================================================
    # PHASE A: Instant skeleton (0ms, no LLM)
    # ==========================================================================

    # Build constraints_applied from static data (no LLM)
    constraint_list = _get_constraints_as_list(plan.destination)
    constraints_applied = [
        {
            "rule": c["desc"],
            "type": c["type"],
            "severity": c["severity"],
            "reason": c["desc"],
        }
        for c in constraint_list
    ]

    # Fetch destination gallery ("Vibe Trio") if available
    dest_key = plan.destination.lower().strip()
    gallery_images = []
    if dest_key in DEMO_MANIFEST:
        gallery_images = DEMO_MANIFEST[dest_key].get("destination_gallery", [])

    # FALLBACK: Generate curated images for destinations without curated gallery
    # This ensures the Magazine Layout always has visual content
    if not gallery_images:
        gallery_images = get_destination_gallery(plan.destination)

    # Build skeleton section — travel_intelligence is empty (populated by Phase B)
    section = build_local_expert_section(
        destination=plan.destination,
        one_liner=f"Your adventure in {plan.destination}",
        bullets=[c["desc"] for c in constraint_list[:3]],
        must_dos=[],
        logistics_notes=[],
        constraints_applied=constraints_applied,
        content_added=[],
        gallery_images=gallery_images,
        travel_intelligence={},
    )

    # Emit skeleton to state immediately (before any background tasks fire)
    from app.debug_utils import _debug_log

    incoming_sections = state.metadata.get("strategy_sections", [])
    _debug_log(
        f"local_expert: BEFORE update - {len(incoming_sections)} sections, "
        f"types={[s.get('specialist_type') for s in incoming_sections]}"
    )

    upsert_section(state.metadata, section, mode="appendable")

    outgoing_sections = state.metadata.get("strategy_sections", [])
    _debug_log(
        f"local_expert: AFTER update - {len(outgoing_sections)} sections, "
        f"types={[s.get('specialist_type') for s in outgoing_sections]}"
    )

    mark_topic_executed(state.metadata, "local_expert")
    log("LOCAL_EXPERT", f"Skeleton built: {len(constraints_applied)} constraints from static data")

    # ==========================================================================
    # CONCURRENT SPECIALIST FIRE (unchanged from original)
    # Fire niche specialist LLM calls in background while we (optionally) run
    # our own enrichment. The specialist node checks
    # state.metadata["parallel_llm_results"] and skips its own LLM calls
    # if results are already cached there.
    # ==========================================================================
    specialist_task = None
    niche_topics = [s for s in state.pending_specialists if s != "local_expert"]

    if niche_topics and plan.destination:
        trip_settings = get_trip_settings(state)
        # Snapshot immutable plan values — avoid capturing live reference across await yield
        _destination = plan.destination
        _start_date = plan.start_date
        _end_date = plan.end_date
        _skill = trip_settings.activity_settings.skill_level
        _day_prefs = trip_settings.activity_settings.day_preferences

        async def _fire_specialist_llm() -> dict:
            from app.db import _get_async_session_factory
            from app.planner.nodes.vertical_specialist import (
                generate_all_specialists_parallel,
            )

            async_session_factory = _get_async_session_factory()
            async with async_session_factory() as db:
                results = await generate_all_specialists_parallel(
                    topics=niche_topics,
                    destination=_destination,
                    trip_plan=plan,
                    db=db,
                    skill_level=_skill,
                    day_preferences=_day_prefs,
                )
            return {k: v.model_dump() if v else None for k, v in results.items()}

        specialist_task = asyncio.create_task(_fire_specialist_llm())
        log("LOCAL_EXPERT", f"Fired specialist LLM in background: {niche_topics}")

    # ==========================================================================
    # PHASE B: Background LLM enrichment (non-blocking)
    # Runs asynchronously after skeleton is in state. Writes travel_intelligence
    # back to DB once the LLM call resolves.
    # ==========================================================================
    if settings.local_expert_use_llm:
        # Snapshot all values needed by the background closure — no live state capture
        _session_id = state.metadata.get("session_id")
        _b_destination = plan.destination
        _b_start_date = plan.start_date
        _b_end_date = plan.end_date
        _b_adults = plan.adults
        _b_children = plan.children

        # Build the prompt for the background LLM call
        prompts_dir = Path(__file__).parent.parent.parent / "prompts" / "specialists"
        prompt_file = prompts_dir / "local_expert.txt"

        if prompt_file.exists():
            system_prompt = prompt_file.read_text()
        else:
            system_prompt = """You are a local logistics expert. Provide:
1. Constraints: Opening hours, booking requirements, seasonal considerations
2. Recommendations: Transit passes, efficiency tips, cultural notes
Output as JSON with "constraints" and "recommendations" arrays."""

        # Inject known constraints as grounding context
        constraint_context = _get_constraint_context(_b_destination)
        if constraint_context:
            system_prompt += constraint_context

        system_prompt += (
            "\n\nRespond ONLY with valid JSON (no markdown fences, no commentary) "
            f"matching this schema:\n{_LOCAL_EXPERT_SCHEMA_JSON}"
        )

        user_context = (
            f"Destination: {_b_destination}\n"
            f"Dates: {_b_start_date or 'Not specified'} to {_b_end_date or 'Not specified'}\n"
            f"Travelers: {_b_adults} adults" + (f", {_b_children} children" if _b_children else "")
        )

        # Snapshot prompt strings so the closure is self-contained
        _system_prompt = system_prompt
        _user_context = user_context

        async def _enrich() -> None:
            """Background LLM enrichment — writes travel_intelligence to DB."""
            try:
                llm = get_llm_by_model(
                    settings.local_expert_model,
                    temperature=0.3,
                    max_retries=0,
                    max_tokens=8000,
                )
                log("LOCAL_EXPERT", f"Phase B: calling LLM ({settings.local_expert_model})...")

                raw = await asyncio.wait_for(
                    llm.ainvoke(
                        [
                            SystemMessage(content=_system_prompt),
                            HumanMessage(content=_user_context),
                        ]
                    ),
                    timeout=60,
                )
                log("LOCAL_EXPERT", "Phase B: LLM call completed")

                content = extract_json_content(raw)
                if not content:
                    log("LOCAL_EXPERT", "Phase B: LLM returned empty content — skipping persist")
                    return

                response = LocalExpertOutput.model_validate_json(content)

                token_usage = extract_token_usage(raw, model=settings.local_expert_model)
                if token_usage:
                    log("LOCAL_EXPERT", f"Phase B: token usage: {token_usage}")

                if _session_id:
                    await _persist_travel_intelligence(_session_id, response)
                    log(
                        "LOCAL_EXPERT",
                        f"Phase B: travel_intelligence persisted for session {_session_id}",
                    )
                else:
                    log(
                        "LOCAL_EXPERT",
                        "Phase B: no session_id in metadata — skipping DB persist",
                    )

            except asyncio.CancelledError:
                # Background tasks may be cancelled on shutdown — log and exit cleanly
                logger.debug("LOCAL_EXPERT Phase B: enrichment task cancelled")
            except (ValidationError, json.JSONDecodeError, asyncio.TimeoutError, ValueError) as e:
                import traceback

                from app.debug_utils import _debug_error

                _debug_error(
                    f"LOCAL_EXPERT Phase B parse/timeout error: {e}\n{traceback.format_exc()}"
                )
                log("LOCAL_EXPERT", f"Phase B: non-fatal LLM error: {type(e).__name__}")
            except Exception as e:
                import traceback

                from app.debug_utils import _debug_error

                _debug_error(
                    f"LOCAL_EXPERT Phase B unexpected error: {e}\n{traceback.format_exc()}"
                )
                log("LOCAL_EXPERT", f"Phase B: non-fatal unexpected error: {type(e).__name__}")

        # Stash enrichment coroutine-factory in module-level dict so streaming.py can fire it
        # after db.commit() — avoids cancellation by the graph's asyncio.timeout() context
        # and avoids the SSE pipeline stomping enriched data with the Phase A skeleton.
        # Function references cannot survive JSON serialization through state_to_session_state
        # so we use a module-level dict keyed by session_id instead of state.metadata.
        if _session_id:
            async with _pending_lock:
                if len(_pending_enrichments) >= _MAX_PENDING_ENRICHMENTS:
                    oldest = next(iter(_pending_enrichments))
                    _pending_enrichments.pop(oldest)
                    logger.warning("[LOCAL_EXPERT] Evicting stale enrichment for %s", oldest)
                _pending_enrichments[_session_id] = (_enrich, time.monotonic())
            log("LOCAL_EXPERT", "Phase B: enrichment stashed for post-commit firing")
        else:
            log("LOCAL_EXPERT", "Phase B: no session_id — enrichment skipped")
    else:
        log("LOCAL_EXPERT", "LLM disabled (local_expert_use_llm=False) — skeleton only")

    # ==========================================================================
    # Collect specialist results — runs even if Phase B is non-blocking;
    # prefetch is independent and benefits downstream node.
    # ==========================================================================
    if specialist_task is not None:
        try:
            specialist_results = await specialist_task
            existing = state.metadata.get("parallel_llm_results", {})
            existing.update(specialist_results)
            state.metadata["parallel_llm_results"] = existing
            log(
                "LOCAL_EXPERT",
                f"Specialist pre-fetch done: {list(specialist_results.keys())} "
                f"({sum(1 for v in specialist_results.values() if v)} succeeded)",
            )
        except Exception as e:
            log("LOCAL_EXPERT", f"Specialist pre-fetch failed (non-fatal): {e}")
            # Non-fatal — specialist node will fire its own LLM calls

    state.metadata["local_expert_ran"] = True  # Persistent flag to prevent double execution
    state.metadata["last_executed_specialist"] = "local_expert"  # Track for downstream
    state.active_specialist = None  # Clear for multi-specialist support
    return state


# =============================================================================
# Background Persistence Helper
# =============================================================================


async def _persist_travel_intelligence(session_id: str, response: LocalExpertOutput) -> None:
    """Write enriched travel_intelligence to the local_expert section in the DB document.

    Called from the Phase B background task after LLM enrichment completes.
    Looks up the PlanDocument by session token, finds the local_expert section,
    and updates travel_intelligence + constraints_applied + content_added in-place.

    Silently returns (no-op) if the document or section is not found.
    """
    from app.crud_document import get_document, get_document_data, save_document_data
    from app.crud_trip import get_session_by_token
    from app.db import _get_async_session_factory

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

    async_session_factory = _get_async_session_factory()
    async with async_session_factory() as db:
        # Look up session by token to get the ORM Session object
        db_session = await get_session_by_token(db, session_id)
        if not db_session:
            logger.debug(f"LOCAL_EXPERT _persist: session token not found in DB: {session_id!r}")
            return

        doc = await get_document(db, session=db_session)
        if not doc:
            logger.debug(f"LOCAL_EXPERT _persist: no PlanDocument for session {db_session.id}")
            return

        # Parse, update local_expert section, save
        data = get_document_data(doc)
        sections = data.strategy_sections or []
        updated = False
        for section in sections:
            # StrategySection objects from get_document_data() are always Pydantic models
            if section.specialist_type != "local_expert":
                continue
            section.travel_intelligence = travel_intelligence
            if response.constraints:
                section.constraints_applied = [
                    {
                        "rule": c.description,
                        "type": c.type,
                        "severity": c.severity,
                        "reason": c.description,
                    }
                    for c in response.constraints
                ]
            if response.recommendations:
                section.content_added = [
                    {
                        "title": r.title,
                        "description": r.description,
                        "type": r.category,
                        "logic_hook": r.logic_hook,
                    }
                    for r in response.recommendations
                ]
            if response.destination_overview and response.destination_overview.tagline:
                section.one_liner = response.destination_overview.tagline
            updated = True
            break

        if not updated:
            logger.debug("LOCAL_EXPERT _persist: local_expert section not found in document")
            return

        await save_document_data(db, doc=doc, data=data, updated_by="planner")
        await db.commit()
        logger.debug("LOCAL_EXPERT _persist: travel_intelligence written to DB")
