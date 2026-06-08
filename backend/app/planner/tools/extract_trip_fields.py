"""
extract_trip_fields tool -- wraps router extraction pipeline.

Reuses _classify_and_extract_with_llm() and _validate_extraction() from
router_extraction.py. Returns extracted fields as a flat dict; state
mutation happens in TurnLifecycleMiddleware, not here.

When running inside a ``create_agent`` graph the ``InjectedState``
annotation supplies the current trip context automatically -- the LLM
only needs to provide ``user_message``.
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
    remove_all_activities: bool = False
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
    # When a genuine destination SWITCH is requested on an already-committed trip,
    # the switch is rejected (destination is locked to the current itinerary) and
    # this carries the requested destination so the terminal model can advise the
    # traveler to Reset and start a new trip. None on every other turn.
    destination_switch_blocked: Optional[str] = None

    # Metadata
    fields_changed: List[str] = Field(default_factory=list)
    date_auto_adjustments: List[Dict[str, str]] = Field(default_factory=list)
    # token_usage carries int counts plus a "model" string (from
    # extract_token_usage), so values are heterogeneous.
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
    if result.remove_all_activities:
        changed.append("remove_all_activities")
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
    # InjectedState -- auto-populated when running inside create_agent;
    # invisible to the LLM's tool-calling schema.  Supplies the authoritative
    # prior trip context so the LLM never needs to echo back state it holds.
    state: Annotated[Optional[dict], InjectedState] = None,
) -> dict:
    """Record or change trip fields and preferences from the user's message.

    Call this FIRST -- before any searching -- whenever the user states or
    changes ANY of: destination, origin, dates/duration, traveler counts,
    budget, activity interests, OR booking preferences. Booking preferences
    explicitly include hotel star rating ("5-star hotels only"), hotel style,
    flight cabin class ("business class"), direct-flights-only, and similar
    refinements. A preference refinement like "5-star hotels only" or "I'm
    flying from San Francisco" IS a trip-detail change -- do not skip straight
    to search_tiles; call extract_trip_fields first so the change is recorded."""
    from app.planner.nodes.router_extraction import (
        RouterOutput,
        _classify_and_extract_with_llm,
    )

    # Prior trip context comes exclusively from InjectedState, which is
    # AUTHORITATIVE. When state is present (always, in-loop) we read the prior
    # values from trip_plan; otherwise (e.g. an offline unit test) we fall back
    # to empty defaults so every extracted field reads as a change.
    current_destination: str = ""
    current_origin: str = ""
    current_start_date: str = ""
    current_end_date: str = ""
    current_adults: int = 1
    current_children: int = 0
    current_budget: float = 0
    current_categories: str = ""  # comma-separated
    if state is not None:
        trip_plan: dict[str, Any] = state.get("trip_plan", {})
        current_destination = trip_plan.get("destination", "") or ""
        current_origin = trip_plan.get("origin", "") or ""
        current_start_date = trip_plan.get("start_date", "") or ""
        current_end_date = trip_plan.get("end_date", "") or ""
        current_adults = trip_plan.get("adults", 1) or 1
        current_children = trip_plan.get("children", 0) or 0
        current_budget = trip_plan.get("budget", 0) or 0
        current_categories = ",".join(trip_plan.get("activity_categories", []) or [])

    # InjectedState is AUTHORITATIVE for the current turn's message, not just
    # prior context. The create_agent model intermittently passes a garbled
    # ``user_message`` -- e.g. the whole conversation history concatenated
    # WITHOUT separators ("...baliJul 1 - Jul 7remove diving") -- which makes the
    # router read a smushed instruction and recompute dates/duration from earlier
    # turns (e.g. "10 days" + "Jul 1" -> end = Jul 10), silently overriding an
    # explicit later range. Prefer the latest real HumanMessage from state so
    # extraction is robust to whatever arg the model fabricated.
    extraction_message = user_message
    if state is not None:
        for _msg in reversed(state.get("messages", []) or []):
            _is_human = type(_msg).__name__ == "HumanMessage" or (
                isinstance(_msg, dict) and _msg.get("type") == "human"
            )
            if not _is_human:
                continue
            _content = getattr(_msg, "content", None)
            if _content is None and isinstance(_msg, dict):
                _content = _msg.get("content")
            if isinstance(_content, str) and _content.strip():
                extraction_message = _content
            break

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
        router_output, token_usage = await _classify_and_extract_with_llm(
            extraction_message, state_proxy
        )
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
        remove_all_activities=router_output.remove_all_activities,
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

    # 3b. The trip destination is LOCKED once a trip has one: switching it
    # invalidates the entire plan, so it is NEVER applied mid-itinerary (a new
    # destination is started via Reset). When the router extracts a destination that
    # differs from the current one, there are two cases:
    #   (a) a QUESTION or sub-locality mention -- e.g. "how would I get from the
    #       airport to Canggu?" (question_type set and/or planning_intent="exploring",
    #       "asking without committing"). Drop ONLY the destination (and any
    #       co-extracted dates/duration, which describe that other place, not a change
    #       to the current timeline); genuine current-trip refinements bundled in the
    #       same message (e.g. "...and add diving") still apply. Without this,
    #       _merge_trip_fields would read a stray place name as a destination change,
    #       wipe the WHOLE plan, and the cleared day_cards would re-arm the post-loop
    #       auto-build -- regenerating the trip on a question.
    #   (b) a genuine SWITCH request -- e.g. "change to Tokyo, July 10-15" (a COMMIT:
    #       the router tags planning_intent="modifying"/"ready" and no question_type,
    #       since the taxonomy has no "change destination" topic). The ENTIRE message
    #       is about the rejected destination, so NOTHING from it applies to the locked
    #       trip -- not the bundled dates/budget/activities/removals/settings. Reset the
    #       extraction to carry only intent + the ``destination_switch_blocked`` advisory
    #       so the terminal model tells the traveler to Reset to start a new trip there.
    # No existing destination -> first-time set is untouched. Geographic-knowledge-
    # free: it uses only the router's own intent signals, never a hard-coded place list.
    if (
        current_destination
        and result.destination
        and result.destination.strip().lower() != current_destination.strip().lower()
    ):
        _requested = result.destination
        _is_question_turn = bool(result.question_type) or result.planning_intent == "exploring"
        if _is_question_turn:
            result.destination = None
            result.destination_iata = None
            # Dates/duration in a question about another place are not a timeline edit.
            result.start_date = None
            result.end_date = None
            result.duration_days = None
            logger.info(
                "[extract_trip_fields] Locked destination (question): dropped "
                "extracted=%r (question_type=%r); trip stays %r",
                _requested,
                result.question_type,
                current_destination,
            )
        else:
            # Reject the whole pivot: rebuild a clean result carrying only intent +
            # the switch advisory. _detect_changed_fields then reports no changes, so
            # _merge_trip_fields applies nothing to the locked trip.
            result = TripFieldsResult(
                intent=result.intent,
                confidence=result.confidence,
                reasoning=result.reasoning,
                question_type=result.question_type,
                planning_intent=result.planning_intent,
                destination_switch_blocked=_requested,
                # Preserve cost telemetry; everything else is intentionally dropped.
                token_usage=result.token_usage,
            )
            logger.info(
                "[extract_trip_fields] Locked destination (switch blocked): rejected "
                "pivot to %r and all bundled fields; trip stays %r",
                _requested,
                current_destination,
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
