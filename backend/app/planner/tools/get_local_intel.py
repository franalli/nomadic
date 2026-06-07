"""
get_local_intel tool -- wraps local expert Phase A (instant skeleton).

Builds the Trip Overview strategy card from static constraint data and
placeholder images. Phase B (background LLM enrichment) is stashed for
post-commit firing via the same _pending_enrichments mechanism used by the
current local_expert node.

Returns a section dict + constraints list + enrichment status.
State mutation happens in TurnLifecycleMiddleware, not here.
"""

import logging
import time
from datetime import UTC, datetime
from typing import Any, Dict, List

from langchain.tools import ToolRuntime
from langchain_core.tools import tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    """UTC timestamp for enrichment status snapshots."""
    return datetime.now(UTC).isoformat()


# Minimum constraint floor for consistent Travel Intel card density. Mirrors
# ``_run_local_expert`` in local_expert.py: static constraint scaffolding was
# removed (real constraints now come from LLM enrichment), so the skeleton
# seeds these generic fallbacks until Phase B enrichment overwrites them.
_MIN_CONSTRAINT_FLOOR = 6
# ``generic_fallback: True`` marks these as boilerplate travel-info floor (visa,
# insurance, etc.) so the planner prompt can filter them OUT of the model's
# per-turn context (build_trip_state_summary) — otherwise the model re-lists this
# generic checklist in chat every turn. They still flow into the plan data / UI
# (strategy_sections), which renders them independently of the model context.
_GENERIC_FALLBACK_CONSTRAINTS: List[Dict[str, Any]] = [
    {
        "rule": "Check visa requirements before travel",
        "type": "visa",
        "severity": "warning",
        "reason": "Check visa requirements before travel",
        "generic_fallback": True,
    },
    {
        "rule": "Travel insurance recommended for international trips",
        "type": "safety",
        "severity": "info",
        "reason": "Travel insurance recommended for international trips",
        "generic_fallback": True,
    },
    {
        "rule": "Carry photocopies of passport and important documents",
        "type": "safety",
        "severity": "info",
        "reason": "Carry photocopies of passport and important documents",
        "generic_fallback": True,
    },
    {
        "rule": "Register with your embassy for safety alerts",
        "type": "safety",
        "severity": "info",
        "reason": "Register with your embassy for safety alerts",
        "generic_fallback": True,
    },
    {
        "rule": "Confirm hotel bookings and transfers before departure",
        "type": "booking_window",
        "severity": "info",
        "reason": "Confirm hotel bookings and transfers before departure",
        "generic_fallback": True,
    },
    {
        "rule": "Check local currency and exchange options",
        "type": "money",
        "severity": "info",
        "reason": "Check local currency and exchange options",
        "generic_fallback": True,
    },
]


def _build_skeleton_constraints() -> List[Dict[str, Any]]:
    """Build the Phase A constraint list from generic fallbacks.

    The current local_expert node no longer ships static per-destination
    constraint scaffolding; the skeleton starts empty and is padded with
    generic fallbacks up to ``_MIN_CONSTRAINT_FLOOR``.
    """
    constraints: List[Dict[str, Any]] = []
    existing_rules: set[str] = set()
    for fb in _GENERIC_FALLBACK_CONSTRAINTS:
        if fb["rule"] not in existing_rules and len(constraints) < _MIN_CONSTRAINT_FLOOR:
            constraints.append(dict(fb))
            existing_rules.add(fb["rule"])
    return constraints


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool
async def get_local_intel(
    destination: str,
    start_date: str = "",
    end_date: str = "",
    travelers: str = "2 adults",
    session_id: str = "",
    runtime: ToolRuntime = None,  # injected by create_agent; excluded from the LLM schema
) -> dict:
    """Get local travel intelligence for a destination. Returns a Trip
    Overview strategy card with images, constraints, and cultural tips.
    Always call this for new destinations.

    Parameters
    ----------
    session_id : str
        Session token passed from agent state. Required for Phase B
        enrichment to persist travel_intelligence to the DB. If empty,
        runtime.config.configurable.thread_id is used when available.
    """
    from app.config import settings
    from app.data.demo_curation import DEMO_MANIFEST
    from app.placeholders import get_destination_gallery
    from app.planner.nodes.local_expert import (
        _MAX_PENDING_ENRICHMENTS,
        # _pending_enrichments and _pending_lock are module-level shared state
        # from local_expert.py. This is INTENTIONAL: both the local_expert graph
        # node and this tool stash Phase B enrichment coroutine-factories in the
        # same dict so that streaming.py can fire them from a single lookup after
        # db.commit(). The _active_destination_enrichments set (accessed inside
        # build_enrichment_closure) provides cross-path deduplication so the same
        # destination is never enriched concurrently by both code paths.
        _pending_enrichments,
        _pending_lock,
        build_enrichment_closure,
    )
    from app.planner.services.section_builder import build_local_expert_section

    # Derive session_id from runtime config when the LLM omits it in tool args.
    resolved_session_id = (session_id or "").strip()
    if not resolved_session_id and runtime is not None:
        runtime_config = getattr(runtime, "config", {}) or {}
        if isinstance(runtime_config, dict):
            configurable = runtime_config.get("configurable", {})
            if isinstance(configurable, dict):
                resolved_session_id = str(configurable.get("thread_id") or "").strip()

    # ------------------------------------------------------------------
    # Parse travelers string ("2 adults", "2 adults, 1 child", etc.)
    # ------------------------------------------------------------------
    adults = 2
    children = 0
    try:
        parts = travelers.lower().replace(",", " ").split()
        for i, part in enumerate(parts):
            if "adult" in part and i > 0:
                adults = int(parts[i - 1])
            elif "child" in part and i > 0:
                children = int(parts[i - 1])
            elif "kid" in part and i > 0:
                children = int(parts[i - 1])
    except (ValueError, IndexError):
        pass  # Keep defaults

    # ------------------------------------------------------------------
    # PHASE A: Instant skeleton (no LLM)
    # ------------------------------------------------------------------
    # The current local_expert node no longer ships static per-destination
    # constraint scaffolding -- real constraints come from Phase B LLM
    # enrichment.  Seed the skeleton with the same generic fallback floor the
    # node uses so the Travel Intel card always has enough density.
    constraints_applied: List[Dict[str, Any]] = _build_skeleton_constraints()

    # Destination gallery ("Vibe Trio")
    dest_key = destination.lower().strip()
    gallery_images: List[Dict[str, Any]] = []
    if dest_key in DEMO_MANIFEST:
        gallery_images = DEMO_MANIFEST[dest_key].get("destination_gallery", [])
    if not gallery_images:
        gallery_images = get_destination_gallery(destination)

    one_liner = f"Your adventure in {destination}"

    # Principles stay empty in the skeleton; the LLM enrichment populates them.
    principles: List[str] = []

    # Must-dos stay empty in the skeleton (parity with _run_local_expert);
    # Phase B enrichment fills them when LLM enrichment is enabled.
    must_dos: List[str] = []

    # Seed content_added so the synchronous skeleton already carries some
    # density (Phase B enrichment adds the rich neighborhood/transfer detail
    # later). An empty content_added reads as "feasible but empty" to the
    # section-content validator. These tips render in the plan panel only -- they
    # do NOT reach the model's per-turn context or the grounding allowlist
    # (local_expert sections are excluded from tile injection in coordinator.py).
    content_added: List[Dict[str, Any]] = [
        {
            "type": "overview",
            "title": f"{destination} travel essentials",
            "description": one_liner,
        }
    ]
    for c in constraints_applied:
        title = c.get("label") or c.get("rule")
        if title:
            content_added.append(
                {
                    "type": "tip",
                    "title": str(title),
                    "description": c.get("reason", "") or "",
                }
            )

    section = build_local_expert_section(
        destination=destination,
        one_liner=one_liner,
        bullets=[],
        must_dos=must_dos,
        logistics_notes=[],
        constraints_applied=constraints_applied,
        content_added=content_added,
        gallery_images=gallery_images,
        travel_intelligence={},
        principles=principles,
    )
    section["local_expert_enrichment"] = {
        "state": "pending" if settings.local_expert_use_llm else "ready",
        "error_code": None if settings.local_expert_use_llm else "disabled",
        "updated_at": _utc_now_iso(),
    }

    # ------------------------------------------------------------------
    # PHASE B: Stash enrichment for post-commit firing
    # ------------------------------------------------------------------
    enrichment_status = "skeleton_only"

    if settings.local_expert_use_llm:
        enrich_fn = build_enrichment_closure(
            destination=destination,
            start_date=start_date or None,
            end_date=end_date or None,
            adults=adults,
            children=children,
            session_id=resolved_session_id,
        )
        if enrich_fn is not None:
            enrichment_status = "pending"
            # Stash in module-level dict (same mechanism as local_expert node).
            # Fall back to destination key only if no session_id is available.
            enrich_key = (
                resolved_session_id if resolved_session_id else f"tool_local_intel_{dest_key}"
            )
            async with _pending_lock:
                if len(_pending_enrichments) >= _MAX_PENDING_ENRICHMENTS:
                    oldest = next(iter(_pending_enrichments))
                    _pending_enrichments.pop(oldest)
                    logger.warning("[get_local_intel] Evicting stale enrichment for %s", oldest)
                _pending_enrichments[enrich_key] = (enrich_fn, time.monotonic())
            logger.debug("[get_local_intel] Phase B stashed for %s", destination)

    logger.debug(
        "[get_local_intel] Skeleton built for %s: %d constraints, %d gallery images",
        destination,
        len(constraints_applied),
        len(gallery_images),
    )

    return {
        "section": section,
        "constraints": constraints_applied,
        "gallery_images": gallery_images,
        "enrichment_status": enrichment_status,
        "destination": destination,
    }
