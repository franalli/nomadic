"""
get_specialist_advice tool -- wraps vertical_specialist LLM pipeline.

Runs feasibility check + LLM specialist generation + strategy section
building for Tier 1 topics (diving, hiking, skiing, cycling, surfing,
climbing, sailing, wildlife_safari).

Returns specialist output as a flat dict; state mutation happens in
TurnLifecycleMiddleware, not here.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------


class SpecialistAdviceResult(BaseModel):
    """Specialist advice output for a single topic."""

    topic: str
    feasibility_status: str = "feasible"  # feasible | caveat | infeasible
    feasibility_reason: Optional[str] = None
    alternative_suggestion: Optional[str] = None
    activities: List[Dict[str, Any]] = Field(default_factory=list)
    constraints: List[Dict[str, Any]] = Field(default_factory=list)
    content_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    strategy_section: Dict[str, Any] = Field(default_factory=dict)
    enhancements: List[str] = Field(default_factory=list)
    # token_usage removed: generate_specialist_output_llm() doesn't expose it


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_trip_plan_proxy(
    destination: str,
    start_date: str,
    end_date: str,
) -> Any:
    """Build a minimal TripPlan with fields needed by generate_specialist_output_llm.

    The function accesses trip_plan.{destination, start_date, end_date, adults, children}.
    """
    from app.planner.state.graph_state import TripPlan

    return TripPlan(
        destination=destination or None,
        start_date=start_date or None,
        end_date=end_date or None,
        adults=2,
        children=0,
    )


def _parse_day_preferences(day_preferences: str, topic: str) -> Optional[int]:
    """Parse day_preferences JSON string to extract target count for this topic.

    Accepts either a JSON object ({"diving": 5, "hiking": 3}) or a plain integer.
    Returns None if not set or unparseable.
    """
    if not day_preferences:
        return None
    stripped = day_preferences.strip()
    if not stripped:
        return None

    # Try plain integer first
    try:
        return int(stripped)
    except ValueError:
        pass

    # Try JSON object
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, dict):
            return parsed.get(topic)
        if isinstance(parsed, int):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass

    return None


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool
async def get_specialist_advice(
    topic: str,
    destination: str,
    start_date: str = "",
    end_date: str = "",
    skill_level: str = "beginner",
    day_preferences: str = "",
) -> dict:
    """Get domain expert advice for a specialist activity (diving, hiking,
    skiing, cycling, surfing). Returns feasibility, recommended activities,
    safety constraints, and a strategy section."""
    from app.placeholders import get_activity_image
    from app.planner.nodes.vertical_specialist import (
        LLMSpecialistOutput,
        generate_specialist_output_llm,
    )
    from app.planner.services.feasibility_service import check_feasibility
    from app.planner.services.section_builder import build_specialist_section
    from app.planner.specialist_registry import (
        TIER1_SPECIALIST_NAMES,
    )
    from app.planner.specialist_registry import (
        get as get_specialist_config,
    )

    topic_lower = topic.lower().strip()

    # 1. Look up specialist config from registry
    config = get_specialist_config(topic_lower)
    if config is None:
        logger.warning(
            "[get_specialist_advice] Unknown topic '%s' -- not in registry",
            topic_lower,
        )
        fallback = SpecialistAdviceResult(
            topic=topic_lower,
            feasibility_status="unknown",
            feasibility_reason=f"No specialist config found for '{topic_lower}'",
        )
        return fallback.model_dump()

    # 2. Run feasibility check (cached via feasibility_service)
    try:
        feas_status, feas_reason, feas_alt = await check_feasibility(topic_lower, destination)
    except Exception as exc:
        logger.error("[get_specialist_advice] Feasibility check failed: %s", exc)
        feas_status, feas_reason, feas_alt = "feasible", None, None

    # Short-circuit if infeasible
    if feas_status == "infeasible":
        section = build_specialist_section(
            topic=topic_lower,
            destination=destination,
            start_date=start_date or None,
            end_date=end_date or None,
            feasibility_status=feas_status,
            feasibility_reason=feas_reason,
            alternative_suggestion=feas_alt,
            constraints=[],
            content_added=[],
            enhancements=config.enhancements,
            hero_image=None,
            skill_level=skill_level or None,
        )
        result = SpecialistAdviceResult(
            topic=topic_lower,
            feasibility_status=feas_status,
            feasibility_reason=feas_reason,
            alternative_suggestion=feas_alt,
            strategy_section=section,
            enhancements=config.enhancements,
        )
        return result.model_dump()

    # 3. Call LLM specialist generation for Tier 1 topics
    activities: List[Dict[str, Any]] = []
    constraints: List[Dict[str, Any]] = []
    content_blocks: List[Dict[str, Any]] = []

    target_activities = _parse_day_preferences(day_preferences, topic_lower)

    if topic_lower in TIER1_SPECIALIST_NAMES:
        trip_plan_proxy = _build_trip_plan_proxy(
            destination=destination,
            start_date=start_date,
            end_date=end_date,
        )

        try:
            llm_output: Optional[LLMSpecialistOutput] = await generate_specialist_output_llm(
                topic=topic_lower,
                destination=destination,
                trip_plan=trip_plan_proxy,
                db=None,  # No DB session in tool context (skip L2 cache)
                skill_level=skill_level or None,
                target_activities=target_activities,
            )
        except Exception as exc:
            logger.error(
                "[get_specialist_advice] LLM generation failed for %s: %s",
                topic_lower,
                exc,
            )
            llm_output = None

        if llm_output is not None:
            # Override feasibility with LLM result if it disagrees
            if llm_output.feasibility_status == "infeasible":
                feas_status = "infeasible"
                feas_reason = llm_output.feasibility_reason

            # Map activities to content blocks
            for act in llm_output.activities:
                act_dict = act.model_dump()
                hero = get_activity_image(
                    topic_lower,
                    destination,
                    act.title,
                )
                act_dict["image_url"] = hero
                activities.append(act_dict)
                content_blocks.append(
                    {
                        "type": "activity",
                        "specialist_type": topic_lower,
                        "title": act.title,
                        "description": act.description,
                        "location": act.location,
                        "duration_hours": act.duration_hours,
                        "difficulty": act.difficulty,
                        "image_url": hero,
                    }
                )

            # Map constraints. SpecialistConstraintOutput.constraint_type is
            # misnamed -- it actually carries a SEVERITY value ("blocking"/
            # "strong"/"soft"), per vertical_specialist's severity_map. Writing it
            # into the `type` field produced type="blocking", which fails the
            # SpecialistConstraint.type Literal and was silently dropped by
            # validate_plan. Mirror the proven vertical_specialist path: hardcode
            # type="safety" and normalize the severity (lowercase, STRONG default)
            # so mixed-case LLM output ("Blocking") doesn't slip through either.
            _severity_map = {"blocking": "blocking", "strong": "strong", "soft": "soft"}
            for c in llm_output.constraints:
                _severity = _severity_map.get((c.constraint_type or "").lower(), "strong")
                constraints.append(
                    {
                        "constraint_id": c.constraint_id,
                        "type": "safety",
                        "rule": c.constraint_id,
                        "severity": _severity,
                        "applies_to_categories": c.applies_to_categories,
                        "buffer_hours": c.buffer_hours,
                        "reason": c.reason,
                        "label": c.label,
                        "icon": c.icon,
                    }
                )
    else:
        # Non-Tier-1 topic: return registry constraints only (no LLM call)
        logger.debug(
            "[get_specialist_advice] Topic '%s' is not Tier 1 -- skipping LLM",
            topic_lower,
        )

    # Always include hardcoded constraints from registry
    if config.hardcoded_constraints:
        existing_ids = {c.get("constraint_id") for c in constraints}
        for hc in config.hardcoded_constraints:
            if hc["constraint_id"] not in existing_ids:
                constraints.append(hc)

    # 4. Build strategy section
    hero_image = None
    if activities:
        hero_image = activities[0].get("image_url")

    section = build_specialist_section(
        topic=topic_lower,
        destination=destination,
        start_date=start_date or None,
        end_date=end_date or None,
        feasibility_status=feas_status,
        feasibility_reason=feas_reason,
        alternative_suggestion=feas_alt,
        constraints=constraints,
        content_added=content_blocks,
        enhancements=config.enhancements,
        hero_image=hero_image,
        skill_level=skill_level or None,
    )

    # 5. Return result
    result = SpecialistAdviceResult(
        topic=topic_lower,
        feasibility_status=feas_status,
        feasibility_reason=feas_reason,
        alternative_suggestion=feas_alt,
        activities=activities,
        constraints=constraints,
        content_blocks=content_blocks,
        strategy_section=section,
        enhancements=config.enhancements,
    )

    logger.debug(
        "[get_specialist_advice] topic=%s dest=%s status=%s activities=%d constraints=%d",
        topic_lower,
        destination,
        feas_status,
        len(activities),
        len(constraints),
    )

    return result.model_dump()
