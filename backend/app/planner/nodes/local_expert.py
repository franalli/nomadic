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
from datetime import UTC, datetime
from pathlib import Path

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import ValidationError

from app.config import settings
from app.data.demo_curation import DEMO_MANIFEST
from app.placeholders import get_destination_gallery
from app.planner.llm_factory import extract_token_usage, get_llm_by_model
from app.planner.nodes.expert_constraints import (
    LocalConstraint,
    LocalExpertOutput,
    LocalRecommendation,
    _get_constraint_context,
    _get_constraints_as_list,
    _get_static_must_dos,
)
from app.planner.services.section_builder import (
    build_local_expert_section,
    mark_topic_executed,
    upsert_section,
)
from app.planner.state import GraphState
from app.planner.state.typed_meta import get_trip_settings

logger = logging.getLogger(__name__)


# Module-level registry for pending Phase B enrichment coroutine-factories.
# Keyed by session_id so streaming.py can retrieve and fire them after db.commit().
# Function references cannot survive JSON serialization through state_to_session_state,
# so they must live here rather than in state.metadata.
_MAX_PENDING_ENRICHMENTS = 50
_ENRICHMENT_TTL_SECONDS = 120  # 2 minutes
_pending_enrichments: dict[str, tuple[object, float]] = {}  # (factory, monotonic_ts)
_pending_lock = asyncio.Lock()  # Protects _pending_enrichments against coroutine interleaving

_active_destination_enrichments: set[str] = set()
_active_enrichment_lock = asyncio.Lock()


async def cancel_pending_enrichment(session_id: str) -> bool:
    """Cancel a pending Phase B enrichment for a session being deleted.

    Returns True if an enrichment was actually cancelled.
    """
    async with _pending_lock:
        entry = _pending_enrichments.pop(session_id, None)
    if entry is not None:
        logger.info("[LOCAL_EXPERT] Cancelled pending enrichment for session %s", session_id)
        return True
    return False


def _utc_now_iso() -> str:
    """UTC timestamp helper for enrichment status snapshots."""
    return datetime.now(UTC).isoformat()


def _norm_text(value: str) -> str:
    """Normalize strings for deterministic de-duplication."""
    import re

    return re.sub(r"\s+", " ", value.strip().lower())


def _append_constraint(
    out: list[LocalConstraint],
    seen: set[str],
    *,
    type_: str,
    description: str,
    severity: str = "info",
) -> None:
    text = description.strip()
    if not text:
        return
    key = _norm_text(text)
    if key in seen:
        return
    seen.add(key)
    out.append(LocalConstraint(type=type_, description=text, severity=severity))


def _append_recommendation(
    out: list[LocalRecommendation],
    seen: set[str],
    *,
    title: str,
    description: str,
    category: str,
    logic_hook: str = "",
) -> None:
    t = title.strip()
    d = description.strip()
    if not t or not d:
        return
    key = _norm_text(f"{t}::{d}")
    if key in seen:
        return
    seen.add(key)
    out.append(
        LocalRecommendation(
            title=t,
            description=d,
            category=category,
            logic_hook=logic_hook.strip(),
        )
    )


def _enrich_legacy_lists(
    response: LocalExpertOutput,
    existing_constraints: list | None = None,
    existing_recommendations: list | None = None,
) -> LocalExpertOutput:
    """
    Ensure legacy `constraints` and `recommendations` lists are sufficiently rich.

    The frontend Travel Intel card currently consumes these flattened arrays.
    When the model returns sparse legacy arrays but rich typed category fields,
    we deterministically backfill from typed fields to keep UX density consistent.

    Args:
        existing_constraints: Prior-turn constraints to seed dedup set. These
            are carried forward and new items are appended after them.
        existing_recommendations: Prior-turn recommendations for dedup seeding.
    """
    MIN_CONSTRAINTS = 8
    MIN_RECOMMENDATIONS = 8
    MAX_CONSTRAINTS = 12
    MAX_RECOMMENDATIONS = 12

    constraints_out: list[LocalConstraint] = list(existing_constraints or [])
    constraint_seen: set[str] = {_norm_text(c.description) for c in constraints_out}

    for c in response.constraints:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_=c.type or "general",
            description=c.description,
            severity=c.severity or "info",
        )

    recommendations_out: list[LocalRecommendation] = list(existing_recommendations or [])
    recommendation_seen: set[str] = set()
    for r in recommendations_out:
        recommendation_seen.add(_norm_text(f"{r.title}::{r.description}"))
    for r in response.recommendations:
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title=r.title,
            description=r.description,
            category=r.category or "logistics",
            logic_hook=r.logic_hook or "",
        )

    v = response.visa_entry
    if v.key_requirements:
        for req in v.key_requirements[:3]:
            _append_constraint(
                constraints_out,
                constraint_seen,
                type_="visa",
                description=f"Entry requirement: {req}",
                severity="info",
            )
    if v.max_stay_days:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="visa",
            description=f"Typical tourist stay limit is {v.max_stay_days} days",
            severity="info",
        )
    if v.immigration_tip:
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Immigration tip",
            description=v.immigration_tip,
            category="logistics",
            logic_hook="Helps avoid border delays",
        )

    s = response.safety_health
    if s.tap_water_safe is False:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="safety",
            description="Tap water is generally not safe to drink",
            severity="warning",
        )
    for concern in s.common_concerns[:4]:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="safety",
            description=concern,
            severity="warning",
        )
    if s.emergency_number:
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Emergency number",
            description=f"Save {s.emergency_number} in your phone before arrival",
            category="logistics",
            logic_hook="Faster response in emergencies",
        )
    if s.nearest_hospital:
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Tourist-friendly hospital",
            description=s.nearest_hospital,
            category="logistics",
            logic_hook="Useful backup for urgent care",
        )

    m = response.money_costs
    if m.exchange_tip:
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Exchange tip",
            description=m.exchange_tip,
            category="logistics",
            logic_hook="Avoid bad FX rates",
        )
    if m.atm_note:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="money",
            description=m.atm_note,
            severity="info",
        )
    if m.haggling:
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Haggling norm",
            description=m.haggling,
            category="cultural",
            logic_hook="Avoid awkward payment interactions",
        )

    t = response.transportation
    if t.traffic_note:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="transport",
            description=t.traffic_note,
            severity="info",
        )
    if t.ride_apps:
        apps = ", ".join(t.ride_apps[:3])
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Ride apps",
            description=f"Use {apps} for licensed rides",
            category="logistics",
            logic_hook="Reduces taxi scams and pricing surprises",
        )
    if t.airport_to_city:
        first = t.airport_to_city[0]
        details = [first.method]
        if first.price:
            details.append(first.price)
        if first.time:
            details.append(first.time)
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Airport transfer",
            description=" · ".join(details),
            category="logistics",
            logic_hook="Plan arrival transfers before landing",
        )

    c = response.cultural_norms
    if c.dress_code.temples:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="cultural",
            description=f"Temple/church dress code: {c.dress_code.temples}",
            severity="info",
        )
    if c.dress_code.restaurants:
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Restaurant dress norm",
            description=c.dress_code.restaurants,
            category="cultural",
            logic_hook="Avoid denied entry at stricter venues",
        )
    for taboo in c.important_taboos[:3]:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="cultural",
            description=taboo,
            severity="info",
        )

    conn = response.connectivity
    if conn.best_sim_provider:
        desc = conn.best_sim_provider
        if conn.sim_cost:
            desc = f"{desc} ({conn.sim_cost})"
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Best SIM/eSIM option",
            description=desc,
            category="logistics",
            logic_hook="Get data immediately on arrival",
        )
    if conn.essential_apps:
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Essential apps",
            description=", ".join(conn.essential_apps[:4]),
            category="logistics",
            logic_hook="Helps with transport, maps, and payments",
        )

    sea = response.seasonality
    if sea.current_season_tip:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="seasonal",
            description=sea.current_season_tip,
            severity="info",
        )
    if sea.rainy_season:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="seasonal",
            description=f"Rainy season: {sea.rainy_season}",
            severity="info",
        )

    td = response.things_to_do
    for exp in td.must_do[:5]:
        if exp.booking and exp.booking.lower() not in {"walk-in ok", "walk in ok"}:
            _append_constraint(
                constraints_out,
                constraint_seen,
                type_="booking_window",
                description=f"{exp.name}: {exp.booking}",
                severity="warning",
            )
        why_bits = [exp.why] if exp.why else []
        if exp.cost:
            why_bits.append(exp.cost)
        if why_bits:
            _append_recommendation(
                recommendations_out,
                recommendation_seen,
                title=exp.name,
                description=" · ".join(why_bits),
                category="attraction",
                logic_hook="High-value local experience",
            )

    n = response.neighborhoods
    for area in n.where_to_stay[:3]:
        desc = area.vibe or "Recommended area"
        if area.price_range:
            desc = f"{desc} ({area.price_range})"
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title=f"Stay in {area.name}",
            description=desc,
            category="accommodation",
            logic_hook="Better base for your daily routing",
        )

    a = response.accommodation
    if a.book_ahead:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="booking_window",
            description=f"Accommodation booking window: {a.book_ahead}",
            severity="warning",
        )
    if a.booking_platforms:
        _append_recommendation(
            recommendations_out,
            recommendation_seen,
            title="Best booking platforms",
            description=", ".join(a.booking_platforms[:3]),
            category="accommodation",
            logic_hook="Higher availability and clearer cancellation policies",
        )

    scam = response.scams_traps
    for item in scam.common_scams[:3]:
        _append_constraint(
            constraints_out,
            constraint_seen,
            type_="safety",
            description=f"Common scam: {item.name}",
            severity="warning",
        )
        if item.how_to_avoid:
            _append_recommendation(
                recommendations_out,
                recommendation_seen,
                title=f"Avoid {item.name}",
                description=item.how_to_avoid,
                category="scam_warning",
                logic_hook="Reduces fraud risk",
            )

    if len(constraints_out) > MAX_CONSTRAINTS:
        constraints_out = constraints_out[:MAX_CONSTRAINTS]
    if len(recommendations_out) > MAX_RECOMMENDATIONS:
        recommendations_out = recommendations_out[:MAX_RECOMMENDATIONS]

    if len(constraints_out) < MIN_CONSTRAINTS or len(recommendations_out) < MIN_RECOMMENDATIONS:
        logger.debug(
            "LOCAL_EXPERT densifier: constraints=%s recommendations=%s",
            len(constraints_out),
            len(recommendations_out),
        )

    response.constraints = constraints_out
    response.recommendations = recommendations_out
    return response


def _has_rich_local_expert_output(response: LocalExpertOutput) -> bool:
    """Guard against stale sparse cache payloads that degrade Travel Intel quality."""
    constraints_count = len([c for c in response.constraints if c.description.strip()])
    recommendations_count = len(
        [r for r in response.recommendations if (r.title.strip() or r.description.strip())]
    )
    quick_tips_count = len(
        [tip for tip in response.quick_tips if isinstance(tip, str) and tip.strip()]
    )
    total = constraints_count + recommendations_count + quick_tips_count
    return total >= 8 and (constraints_count >= 3 or recommendations_count >= 3)


def _to_travel_intelligence_dict(response: LocalExpertOutput) -> dict:
    """Serialize LocalExpertOutput typed fields into strategy-section travel_intelligence."""
    return {
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


async def _get_cached_local_expert_output(destination: str, log) -> LocalExpertOutput | None:
    """Destination-scoped cache lookup (L1/L2) for local_expert enrichment payload."""
    from app.db import _get_async_session_factory
    from app.services.specialist_cache import get_cached_specialist_output

    async_session_factory = _get_async_session_factory()
    try:
        async with async_session_factory() as cache_db:
            cached_payload = await get_cached_specialist_output(
                cache_db,
                topic="local_expert",
                destination=destination,
                # Destination-scoped key: no dates/day pref/skill.
                start_date=None,
                end_date=None,
                skill_level=None,
                day_pref=None,
            )
    except Exception as cache_err:  # pragma: no cover - defensive
        log("LOCAL_EXPERT", f"Destination cache lookup failed (non-fatal): {cache_err}")
        return None

    if not cached_payload:
        return None

    try:
        return LocalExpertOutput.model_validate(cached_payload)
    except ValidationError:
        log("LOCAL_EXPERT", "Destination cache payload invalid — ignoring cached entry")
        return None


def _build_section_from_cached_output(destination: str, response: LocalExpertOutput) -> dict:
    """Build a fully-hydrated local_expert section from cached LocalExpertOutput."""
    dest_key = destination.lower().strip()
    gallery_images = []
    if dest_key in DEMO_MANIFEST:
        gallery_images = DEMO_MANIFEST[dest_key].get("destination_gallery", [])
    if not gallery_images:
        gallery_images = get_destination_gallery(destination)

    constraints_applied = [
        {
            "rule": c.description,
            "type": c.type,
            "severity": c.severity,
            "reason": c.description,
        }
        for c in response.constraints
    ]
    content_added = [
        {
            "title": r.title,
            "description": r.description,
            "type": r.category,
            "logic_hook": r.logic_hook,
        }
        for r in response.recommendations
    ]
    principles = [p for p in (response.quick_tips or []) if isinstance(p, str)][:4]
    if not principles:
        principles = [c.description for c in response.constraints[:4]]

    must_dos = [exp.name for exp in response.things_to_do.must_do[:5] if exp.name]
    one_liner = (
        response.destination_overview.tagline
        if response.destination_overview and response.destination_overview.tagline
        else f"Your adventure in {destination}"
    )
    bullets = [c.description for c in response.constraints[:3]]

    section = build_local_expert_section(
        destination=destination,
        one_liner=one_liner,
        bullets=bullets,
        must_dos=must_dos,
        logistics_notes=[],
        constraints_applied=constraints_applied,
        content_added=content_added,
        gallery_images=gallery_images,
        travel_intelligence=_to_travel_intelligence_dict(response),
        principles=principles,
    )
    section["local_expert_enrichment"] = {
        "state": "ready",
        "error_code": None,
        "updated_at": _utc_now_iso(),
    }
    return section


# =============================================================================
# Shared Phase B enrichment closure — used by both the local_expert node
# and the get_local_intel tool to avoid duplicated LLM/cache/persist logic.
# =============================================================================


def build_enrichment_closure(
    destination: str,
    start_date: str | None,
    end_date: str | None,
    adults: int,
    children: int,
    session_id: str = "",
    budget: float | None = None,
    vibe: str | None = None,
    origin: str | None = None,
    activity_categories: list[str] | None = None,
) -> object:
    """Build the Phase B enrichment async callable.

    Returns an async function that, when awaited, runs the local expert LLM
    enrichment and persists travel_intelligence to the DB. Both the
    ``local_expert`` graph node and the ``get_local_intel`` agent tool call
    this factory so the enrichment logic lives in exactly one place.

    Parameters
    ----------
    destination : str
        Target destination (e.g. "Bali").
    start_date, end_date : str | None
        Trip date range (ISO-8601 or None).
    adults, children : int
        Traveler counts.
    session_id : str
        Session token for DB persistence. Empty string skips DB writes.
    """
    # Build the prompt from snapshotted values — closure is fully self-contained
    prompts_dir = Path(__file__).parent.parent.parent / "prompts" / "specialists"
    prompt_file = prompts_dir / "local_expert.txt"

    if prompt_file.exists():
        system_prompt = prompt_file.read_text()
    else:
        system_prompt = """You are a local logistics expert. Provide:
1. Constraints: Opening hours, booking requirements, seasonal considerations
2. Recommendations: Transit passes, efficiency tips, cultural notes
Output as JSON with "constraints" and "recommendations" arrays."""

    constraint_context = _get_constraint_context(destination)
    if constraint_context:
        system_prompt += constraint_context

    system_prompt += (
        "\n\nRespond ONLY with valid JSON (no markdown fences, no commentary) "
        "matching the OUTPUT FORMAT above."
    )

    user_context = (
        f"Destination: {destination}\n"
        f"Dates: {start_date or 'Not specified'} to {end_date or 'Not specified'}\n"
        f"Travelers: {adults} adults" + (f", {children} children" if children else "")
    )
    if origin:
        user_context += f"\nOrigin: {origin}"
    if budget:
        user_context += f"\nBudget: ~${budget:,.0f} total"
    if vibe:
        user_context += f"\nTrip vibe: {vibe}"
    if activity_categories:
        user_context += f"\nPlanned activities: {', '.join(activity_categories)}"

    # Snapshot all values so the closure captures only immutable strings/ints
    _system_prompt = system_prompt
    _user_context = user_context
    _destination = destination
    _session_id = session_id or ""

    async def _enrich() -> None:
        """Background LLM enrichment — writes travel_intelligence to DB."""
        destination_key = (_destination or "").strip().lower()
        session_key = _session_id.strip()
        enrichment_key = f"{session_key}::{destination_key}" if destination_key else session_key

        async with _active_enrichment_lock:
            if enrichment_key and enrichment_key in _active_destination_enrichments:
                logger.debug(
                    "LOCAL_EXPERT Phase B: in-flight dedupe HIT for %s/%s — skipping",
                    session_key,
                    destination_key,
                )
                return
            if enrichment_key:
                _active_destination_enrichments.add(enrichment_key)

        try:
            # Destination-scoped cache check (L1 memory -> L2 response_cache)
            from app.db import _get_async_session_factory
            from app.services.specialist_cache import get_cached_specialist_output

            async_session_factory = _get_async_session_factory()
            cached_payload = None
            try:
                async with async_session_factory() as cache_db:
                    cached_payload = await get_cached_specialist_output(
                        cache_db,
                        topic="local_expert",
                        destination=_destination,
                        start_date=None,
                        end_date=None,
                        skill_level=None,
                        day_pref=None,
                    )
            except Exception as cache_err:
                logger.debug("LOCAL_EXPERT Phase B cache lookup failed (non-fatal): %s", cache_err)

            if cached_payload:
                try:
                    response = LocalExpertOutput.model_validate(cached_payload)
                    response = _enrich_legacy_lists(response)
                    if _has_rich_local_expert_output(response):
                        logger.debug("LOCAL_EXPERT Phase B cache HIT for %s", _destination)
                        if _session_id:
                            await _persist_travel_intelligence(
                                _session_id,
                                response,
                                enrichment_state="ready",
                            )
                        return
                    logger.debug(
                        "LOCAL_EXPERT Phase B cache BYPASS for %s: sparse payload",
                        _destination,
                    )
                except ValidationError:
                    logger.debug("LOCAL_EXPERT Phase B cache payload invalid — falling back to LLM")

            llm = get_llm_by_model(
                settings.local_expert_model,
                temperature=0.3,
                max_retries=0,
                max_tokens=5000,
            )
            structured_llm = llm.with_structured_output(
                LocalExpertOutput, include_raw=True, method="function_calling"
            )
            logger.debug("LOCAL_EXPERT Phase B: calling LLM (%s)...", settings.local_expert_model)

            for _attempt in range(2):
                try:
                    raw_result = await asyncio.wait_for(
                        structured_llm.ainvoke(
                            [
                                SystemMessage(content=_system_prompt),
                                HumanMessage(content=_user_context),
                            ]
                        ),
                        timeout=60,
                    )
                    break
                except Exception:
                    if _attempt == 0:
                        logger.debug("LOCAL_EXPERT Phase B: LLM call failed, retrying after 2s...")
                        await asyncio.sleep(2)
                        continue
                    raise
            logger.debug("LOCAL_EXPERT Phase B: LLM call completed")

            parsed = raw_result.get("parsed") if isinstance(raw_result, dict) else None
            if parsed is None:
                if _session_id:
                    await _persist_travel_intelligence(
                        _session_id,
                        None,
                        enrichment_state="failed",
                        error_code="parse_error",
                    )
                logger.debug(
                    "LOCAL_EXPERT Phase B: structured output returned None — marked failed"
                )
                return

            # Gemini returns dict when using class schema; rehydrate to Pydantic
            if isinstance(parsed, dict):
                response = LocalExpertOutput.model_validate(parsed)
            else:
                response = parsed
            response = _enrich_legacy_lists(response)

            # Best-effort cache write for future destination-scoped reuse.
            from app.services.specialist_cache import set_cached_specialist_output

            try:
                async with async_session_factory() as cache_db:
                    await set_cached_specialist_output(
                        cache_db,
                        topic="local_expert",
                        destination=_destination,
                        start_date=None,
                        end_date=None,
                        output=response.model_dump(),
                        skill_level=None,
                        day_pref=None,
                    )
                logger.debug("LOCAL_EXPERT Phase B cache WRITE for %s", _destination)
            except Exception as cache_err:
                logger.debug("LOCAL_EXPERT Phase B cache write failed (non-fatal): %s", cache_err)

            token_usage = extract_token_usage(raw_result, model=settings.local_expert_model)
            if token_usage:
                from app.debug_utils import calculate_llm_cost

                _p = token_usage.get("prompt_tokens", 0)
                _c = token_usage.get("completion_tokens", 0)
                _cost = calculate_llm_cost(settings.local_expert_model, _p, _c)
                logger.debug(
                    "LOCAL_EXPERT Phase B: p=%d c=%d tot=%d $%.4f (%s)",
                    _p,
                    _c,
                    _p + _c,
                    _cost,
                    settings.local_expert_model,
                )

            if _session_id:
                await _persist_travel_intelligence(
                    _session_id,
                    response,
                    enrichment_state="ready",
                )
                logger.debug(
                    "LOCAL_EXPERT Phase B: travel_intelligence persisted for session %s",
                    _session_id,
                )
            else:
                logger.debug("LOCAL_EXPERT Phase B: no session_id — skipping DB persist")

        except asyncio.CancelledError:
            logger.debug("LOCAL_EXPERT Phase B: enrichment task cancelled")
        except (ValidationError, json.JSONDecodeError, asyncio.TimeoutError, ValueError) as e:
            import traceback

            from app.debug_utils import _debug_error

            _debug_error(f"LOCAL_EXPERT Phase B parse/timeout error: {e}\n{traceback.format_exc()}")
            if _session_id:
                error_code = "timeout" if isinstance(e, asyncio.TimeoutError) else "parse_error"
                await _persist_travel_intelligence(
                    _session_id,
                    None,
                    enrichment_state="failed",
                    error_code=error_code,
                )
            logger.debug("LOCAL_EXPERT Phase B: non-fatal LLM error: %s", type(e).__name__)
        except Exception as e:
            import traceback

            from app.debug_utils import _debug_error

            _debug_error(f"LOCAL_EXPERT Phase B unexpected error: {e}\n{traceback.format_exc()}")
            if _session_id:
                await _persist_travel_intelligence(
                    _session_id,
                    None,
                    enrichment_state="failed",
                    error_code="llm_error",
                )
            logger.debug("LOCAL_EXPERT Phase B: non-fatal unexpected error: %s", type(e).__name__)
        finally:
            if enrichment_key:
                async with _active_enrichment_lock:
                    _active_destination_enrichments.discard(enrichment_key)

    return _enrich


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
            cached_constraints = cached_section.get("constraints_applied") or []
            cached_recommendations = cached_section.get("content_added") or []
            if len(cached_constraints) >= 6 and len(cached_recommendations) >= 6:
                log("LOCAL_EXPERT", f"Cache HIT: Reusing cached output for {current_destination}")
                state.metadata["last_executed_specialist"] = "local_expert"
                state.active_specialist = None
                return state  # No-op, output already in state from session restore
            log(
                "LOCAL_EXPERT",
                "Cache BYPASS: existing section too sparse; regenerating enrichment",
            )

    # Session state can be stale (pre-enrichment skeleton). Always check destination-scoped
    # specialist cache before re-running Phase A/Phase B so repeated turns avoid recomputation.
    # Extract prior-turn constraints/recommendations for dedup seeding (Issue 12).
    _prior_constraints: list[LocalConstraint] = []
    _prior_recommendations: list[LocalRecommendation] = []
    if cached_section:
        for cd in cached_section.get("constraints_applied") or []:
            desc = cd.get("rule") or cd.get("reason") or ""
            if desc.strip():
                _prior_constraints.append(
                    LocalConstraint(
                        type=cd.get("type", "general"),
                        description=desc.strip(),
                        severity=cd.get("severity", "info"),
                    )
                )
        for rd in cached_section.get("content_added") or []:
            title = (rd.get("title") or "").strip()
            desc = (rd.get("description") or "").strip()
            if title or desc:
                _prior_recommendations.append(
                    LocalRecommendation(
                        title=title,
                        description=desc,
                        category=rd.get("type") or rd.get("category") or "logistics",
                        logic_hook=rd.get("logic_hook") or "",
                    )
                )

    if settings.local_expert_use_llm:
        cached_response = await _get_cached_local_expert_output(plan.destination, log)
        if cached_response is not None:
            cached_response = _enrich_legacy_lists(
                cached_response,
                existing_constraints=_prior_constraints,
                existing_recommendations=_prior_recommendations,
            )
            if _has_rich_local_expert_output(cached_response):
                section = _build_section_from_cached_output(plan.destination, cached_response)
                upsert_section(state.metadata, section, mode="appendable")
                mark_topic_executed(state.metadata, "local_expert")
                log(
                    "LOCAL_EXPERT",
                    f"Cache HIT (destination L1/L2): reused cached enrichment for {plan.destination}",
                )
                state.metadata["last_executed_specialist"] = "local_expert"
                state.active_specialist = None
                return state
            log(
                "LOCAL_EXPERT",
                f"Cache BYPASS (destination L1/L2): sparse cached enrichment for {plan.destination}",
            )

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

    # Enforce minimum constraint floor (6) for consistent UX density.
    # LLM non-determinism can produce 3 or 12 constraints; this ensures
    # the Travel Intel card always has enough content.
    _MIN_CONSTRAINT_FLOOR = 6
    if len(constraints_applied) < _MIN_CONSTRAINT_FLOOR:
        _existing_rules = {c["rule"] for c in constraints_applied}
        _generic_fallbacks = [
            {
                "rule": "Check visa requirements before travel",
                "type": "visa",
                "severity": "warning",
                "reason": "Check visa requirements before travel",
            },
            {
                "rule": "Travel insurance recommended for international trips",
                "type": "safety",
                "severity": "info",
                "reason": "Travel insurance recommended for international trips",
            },
            {
                "rule": "Carry photocopies of passport and important documents",
                "type": "safety",
                "severity": "info",
                "reason": "Carry photocopies of passport and important documents",
            },
            {
                "rule": "Register with your embassy for safety alerts",
                "type": "safety",
                "severity": "info",
                "reason": "Register with your embassy for safety alerts",
            },
            {
                "rule": "Confirm hotel bookings and transfers before departure",
                "type": "booking_window",
                "severity": "info",
                "reason": "Confirm hotel bookings and transfers before departure",
            },
            {
                "rule": "Check local currency and exchange options",
                "type": "money",
                "severity": "info",
                "reason": "Check local currency and exchange options",
            },
        ]
        for fb in _generic_fallbacks:
            if (
                fb["rule"] not in _existing_rules
                and len(constraints_applied) < _MIN_CONSTRAINT_FLOOR
            ):
                constraints_applied.append(fb)
                _existing_rules.add(fb["rule"])

    # Fetch destination gallery ("Vibe Trio") if available
    dest_key = plan.destination.lower().strip()
    gallery_images = []
    if dest_key in DEMO_MANIFEST:
        gallery_images = DEMO_MANIFEST[dest_key].get("destination_gallery", [])

    # FALLBACK: Generate curated images for destinations without curated gallery
    # This ensures the Magazine Layout always has visual content
    if not gallery_images:
        gallery_images = get_destination_gallery(plan.destination)

    # Build Phase A skeleton — enriched from static data (no LLM)
    # Better one_liner from constraint types
    warning_constraints = [c for c in constraint_list if c["severity"] == "warning"]
    if warning_constraints:
        warning_types = list({c["type"] for c in warning_constraints})
        joined = " & ".join(warning_types[:2])
        one_liner = f"{plan.destination}: review {joined} requirements before your trip"
    else:
        one_liner = f"Your adventure in {plan.destination}"

    # Principles from warning-severity constraints (max 4)
    principles = [c["desc"] for c in warning_constraints[:4]]

    # Keep skeleton must_dos empty when LLM enrichment is disabled.
    must_dos = _get_static_must_dos(plan.destination) if settings.local_expert_use_llm else []

    section = build_local_expert_section(
        destination=plan.destination,
        one_liner=one_liner,
        bullets=[c["desc"] for c in constraint_list[:3]],
        must_dos=must_dos,
        logistics_notes=[],
        constraints_applied=constraints_applied,
        content_added=[],
        gallery_images=gallery_images,
        travel_intelligence={},
        principles=principles,
    )
    section["local_expert_enrichment"] = {
        "state": "pending" if settings.local_expert_use_llm else "ready",
        "error_code": None if settings.local_expert_use_llm else "disabled",
        "updated_at": _utc_now_iso(),
    }

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
        _ts = get_trip_settings(state)
        _activity_cats = (
            list(_ts.activity_settings.categories) if _ts.activity_settings.categories else []
        )

        _enrich = build_enrichment_closure(
            destination=plan.destination,
            start_date=plan.start_date,
            end_date=plan.end_date,
            adults=plan.adults,
            children=plan.children,
            session_id=_session_id or "",
            budget=getattr(plan, "budget", None),
            vibe=getattr(plan, "vibe", None),
            origin=plan.origin,
            activity_categories=_activity_cats or None,
        )

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
            sections = state.metadata.get("strategy_sections", [])
            for s in sections:
                if s.get("specialist_type") == "local_expert":
                    s["local_expert_enrichment"] = {
                        "state": "failed",
                        "error_code": "no_session",
                        "updated_at": _utc_now_iso(),
                    }
                    break
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


async def _persist_travel_intelligence(
    session_id: str,
    response: LocalExpertOutput | None,
    *,
    enrichment_state: str,
    error_code: str | None = None,
) -> None:
    """Persist local_expert enrichment status and optional travel intelligence payload."""
    from app.crud_document import get_document, get_document_data, save_document_data
    from app.crud_trip import get_session_by_token
    from app.db import _get_async_session_factory

    if enrichment_state not in {"ready", "failed"}:
        raise ValueError(f"Invalid enrichment_state: {enrichment_state}")

    travel_intelligence = None
    if response is not None:
        travel_intelligence = _to_travel_intelligence_dict(response)

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
            section.local_expert_enrichment = {
                "state": enrichment_state,
                "error_code": error_code,
                "updated_at": _utc_now_iso(),
            }
            if travel_intelligence is not None:
                section.travel_intelligence = travel_intelligence
                if response.constraints:
                    _enriched_constraints = [
                        {
                            "rule": c.description,
                            "type": c.type,
                            "severity": c.severity,
                            "reason": c.description,
                        }
                        for c in response.constraints
                    ]
                    # Enforce minimum constraint floor (6) for Phase B as well
                    _MIN_PB_FLOOR = 6
                    if len(_enriched_constraints) < _MIN_PB_FLOOR:
                        _pb_rules = {c["rule"] for c in _enriched_constraints}
                        _pb_fallbacks = [
                            {
                                "rule": "Check visa requirements before travel",
                                "type": "visa",
                                "severity": "warning",
                                "reason": "Check visa requirements before travel",
                            },
                            {
                                "rule": "Travel insurance recommended",
                                "type": "safety",
                                "severity": "info",
                                "reason": "Travel insurance recommended",
                            },
                            {
                                "rule": "Carry photocopies of important documents",
                                "type": "safety",
                                "severity": "info",
                                "reason": "Carry photocopies of important documents",
                            },
                            {
                                "rule": "Register with your embassy for alerts",
                                "type": "safety",
                                "severity": "info",
                                "reason": "Register with your embassy for alerts",
                            },
                            {
                                "rule": "Confirm bookings before departure",
                                "type": "booking_window",
                                "severity": "info",
                                "reason": "Confirm bookings before departure",
                            },
                            {
                                "rule": "Check local currency and exchange options",
                                "type": "money",
                                "severity": "info",
                                "reason": "Check local currency and exchange options",
                            },
                        ]
                        for _fb in _pb_fallbacks:
                            if (
                                _fb["rule"] not in _pb_rules
                                and len(_enriched_constraints) < _MIN_PB_FLOOR
                            ):
                                _enriched_constraints.append(_fb)
                                _pb_rules.add(_fb["rule"])
                    section.constraints_applied = _enriched_constraints
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
        logger.debug(
            "LOCAL_EXPERT _persist: enrichment state=%s written to DB (error=%s)",
            enrichment_state,
            error_code,
        )
