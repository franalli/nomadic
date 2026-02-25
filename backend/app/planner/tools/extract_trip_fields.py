"""
extract_trip_fields tool -- wraps router extraction pipeline.

Reuses _classify_and_extract_with_llm() and _validate_extraction() from
router_extraction.py. Returns extracted fields as a flat dict; state
mutation happens in TurnLifecycleMiddleware, not here.

When running inside a ``create_agent`` graph the ``InjectedState``
annotation supplies current trip context automatically -- the LLM does
not need to pass ``current_*`` parameters.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState
from pydantic import BaseModel, Field
from typing_extensions import Annotated

if TYPE_CHECKING:
    from app.planner.state.graph_state import GraphState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result schema
# ---------------------------------------------------------------------------


class TripFieldsResult(BaseModel):
    """Extracted trip fields from user message."""

    # Intent
    intent: str = "PLANNING"  # GREETING | RESET | PLANNING
    confidence: float = 0.8
    reasoning: str = ""

    # Trip fields (only non-None fields were explicitly mentioned)
    destination: Optional[str] = None
    origin: Optional[str] = None
    origin_iata: Optional[str] = None
    destination_iata: Optional[str] = None
    start_date: Optional[str] = None  # YYYY-MM-DD
    end_date: Optional[str] = None
    duration_days: Optional[int] = None
    adults: Optional[int] = None
    children: Optional[int] = None
    budget: Optional[float] = None

    # Specialist / activity detection
    specialist_hints: List[str] = Field(default_factory=list)
    activity_categories: List[str] = Field(default_factory=list)
    activity_day_preferences: Optional[str] = None  # JSON string

    # Modifications
    removal_targets: List[str] = Field(default_factory=list)
    skill_level: Optional[str] = None
    reset_budget: bool = False
    reset_hotel: bool = False

    # Settings
    hotel_min_stars: Optional[int] = None
    hotel_style: Optional[str] = None
    hotel_amenities: List[str] = Field(default_factory=list)
    hotel_location: Optional[str] = None
    flight_direct_only: Optional[bool] = None
    flight_cabin_class: Optional[str] = None

    # Flags
    has_dates_in_message: bool = False
    has_activity_in_message: bool = False
    planning_ready: bool = False
    multi_destination_detected: bool = False
    planning_intent: Optional[str] = None
    question_type: Optional[str] = None

    # Metadata
    fields_changed: List[str] = Field(default_factory=list)
    date_auto_adjustments: List[Dict[str, str]] = Field(default_factory=list)
    token_usage: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_state_proxy(
    current_destination: str,
    current_origin: str,
    current_start_date: str,
    current_end_date: str,
    current_adults: int,
    current_children: int,
    current_budget: float,
    current_categories: str,
) -> "GraphState":
    """Build a minimal GraphState with trip_plan fields for context fingerprinting.

    _classify_and_extract_with_llm accesses state.trip_plan.{destination,
    start_date, end_date} via _build_current_trip_context.  We populate only
    those fields so the extraction prompt contains the right context.
    """
    from app.planner.state.graph_state import GraphState, TripPlan

    plan = TripPlan(
        destination=current_destination or None,
        origin=current_origin or None,
        start_date=current_start_date or None,
        end_date=current_end_date or None,
        adults=current_adults if current_adults else 1,
        children=current_children if current_children else 0,
        budget=current_budget if current_budget else None,
    )
    state = GraphState(trip_plan=plan, metadata={})
    return state


def _detect_changed_fields(
    result: "TripFieldsResult",
    current_destination: str,
    current_origin: str,
    current_start_date: str,
    current_end_date: str,
    current_adults: int,
    current_children: int,
    current_budget: float,
    current_categories: str,
) -> List[str]:
    """Compare extracted fields against current values, return names that changed."""
    changed: List[str] = []

    if result.destination and result.destination != current_destination:
        changed.append("destination")
    if result.origin and result.origin != current_origin:
        changed.append("origin")
    if result.start_date and result.start_date != current_start_date:
        changed.append("start_date")
    if result.end_date and result.end_date != current_end_date:
        changed.append("end_date")
    if result.duration_days is not None:
        changed.append("duration_days")
    if result.adults is not None and result.adults != current_adults:
        changed.append("adults")
    if result.children is not None and result.children != current_children:
        changed.append("children")
    if result.budget is not None and result.budget != current_budget:
        changed.append("budget")
    if result.specialist_hints:
        changed.append("specialist_hints")
    if result.activity_categories:
        prev = {c.strip().lower() for c in current_categories.split(",") if c.strip()}
        new = set(result.activity_categories)
        if new != prev:
            changed.append("activity_categories")
    if result.removal_targets:
        changed.append("removal_targets")
    if result.origin_iata:
        changed.append("origin_iata")
    if result.destination_iata:
        changed.append("destination_iata")
    if result.skill_level:
        changed.append("skill_level")
    if result.hotel_min_stars is not None:
        changed.append("hotel_min_stars")
    if result.hotel_style:
        changed.append("hotel_style")
    if result.hotel_amenities:
        changed.append("hotel_amenities")
    if result.hotel_location:
        changed.append("hotel_location")
    if result.flight_direct_only is not None:
        changed.append("flight_direct_only")
    if result.flight_cabin_class:
        changed.append("flight_cabin_class")
    if result.reset_budget:
        changed.append("reset_budget")
    if result.reset_hotel:
        changed.append("reset_hotel")

    return changed


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


@tool
async def extract_trip_fields(
    user_message: str,
    current_destination: str = "",
    current_origin: str = "",
    current_start_date: str = "",
    current_end_date: str = "",
    current_adults: int = 1,
    current_children: int = 0,
    current_budget: float = 0,
    current_categories: str = "",  # comma-separated
    # InjectedState -- auto-populated when running inside create_agent;
    # invisible to the LLM's tool-calling schema.  When present it
    # overrides the current_* parameters above so the LLM does not need
    # to echo back state it already holds.
    state: Annotated[Optional[dict], InjectedState] = None,
) -> dict:
    """Extract trip planning fields (destination, dates, travelers, budget,
    activities, preferences) from a user message. Call this when the user
    provides or changes trip details."""
    from app.planner.nodes.router_extraction import (
        RouterOutput,
        _classify_and_extract_with_llm,
    )

    # When InjectedState is available, ALWAYS use state values for current_*
    # fields. The LLM may echo user-message values as current_* args, which
    # breaks change detection (e.g. destination "Bali" vs current "Bali").
    if state is not None:
        trip_plan: dict[str, Any] = state.get("trip_plan", {})
        current_destination = trip_plan.get("destination", "")
        current_origin = trip_plan.get("origin", "")
        current_start_date = trip_plan.get("start_date", "")
        current_end_date = trip_plan.get("end_date", "")
        current_adults = trip_plan.get("adults", 1)
        current_children = trip_plan.get("children", 0)
        current_budget = trip_plan.get("budget", 0) or 0

    # 1. Build lightweight state proxy for context fingerprinting
    state_proxy = _build_state_proxy(
        current_destination=current_destination,
        current_origin=current_origin,
        current_start_date=current_start_date,
        current_end_date=current_end_date,
        current_adults=current_adults,
        current_children=current_children,
        current_budget=current_budget,
        current_categories=current_categories,
    )

    # 2. Call core extraction (includes validation + normalization + caching)
    try:
        router_output: RouterOutput
        token_usage: dict
        router_output, token_usage = await _classify_and_extract_with_llm(user_message, state_proxy)
    except Exception as exc:
        logger.error("[extract_trip_fields] Extraction failed: %s", exc)
        # Return a minimal PLANNING result so the agent can continue
        fallback = TripFieldsResult(
            intent="PLANNING",
            confidence=0.0,
            reasoning=f"Extraction error: {type(exc).__name__}",
        )
        return fallback.model_dump()

    # 3. Map RouterOutput fields to TripFieldsResult
    result = TripFieldsResult(
        # Intent
        intent=router_output.intent,
        confidence=router_output.confidence,
        reasoning=router_output.reasoning,
        # Trip fields
        destination=router_output.destination,
        origin=router_output.origin,
        origin_iata=router_output.origin_iata,
        destination_iata=router_output.destination_iata,
        start_date=router_output.start_date,
        end_date=router_output.end_date,
        duration_days=router_output.duration_days,
        adults=router_output.adults,
        children=router_output.children,
        budget=router_output.budget,
        # Specialist / activity
        specialist_hints=router_output.specialist_hints,
        activity_categories=router_output.activity_categories,
        activity_day_preferences=router_output.activity_day_preferences,
        # Modifications
        removal_targets=router_output.removal_targets,
        skill_level=router_output.skill_level,
        reset_budget=router_output.reset_budget,
        reset_hotel=router_output.reset_hotel,
        # Settings
        hotel_min_stars=router_output.hotel_min_stars,
        hotel_style=router_output.hotel_style,
        hotel_amenities=router_output.hotel_amenities,
        hotel_location=router_output.hotel_location,
        flight_direct_only=router_output.flight_direct_only,
        flight_cabin_class=router_output.flight_cabin_class,
        # Flags
        has_dates_in_message=router_output.has_dates_in_message,
        has_activity_in_message=router_output.has_activity_in_message,
        planning_ready=router_output.planning_ready,
        multi_destination_detected=router_output.multi_destination_detected,
        planning_intent=router_output.planning_intent,
        question_type=router_output.question_type,
        # Metadata
        date_auto_adjustments=router_output.date_auto_adjustments,
        token_usage=token_usage,
    )

    # 4. Track which fields changed vs current state
    result.fields_changed = _detect_changed_fields(
        result,
        current_destination=current_destination,
        current_origin=current_origin,
        current_start_date=current_start_date,
        current_end_date=current_end_date,
        current_adults=current_adults,
        current_children=current_children,
        current_budget=current_budget,
        current_categories=current_categories,
    )

    logger.debug(
        "[extract_trip_fields] intent=%s dest=%s changed=%s",
        result.intent,
        result.destination,
        result.fields_changed,
    )

    return result.model_dump()
