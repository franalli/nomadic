"""
Regression tests for build_itinerary using authoritative agent state.

Reproduces the destructive S3 category-change bug: adding a Tier-2 category
on an existing diving plan fired GENERATE_PLAN_NOW, the agent re-ran
search_tiles (passing a non-default ``tiles_json``) then build_itinerary, and
the whole itinerary collapsed to empty "Free Day" blocks with zero map POIs.

Root cause (both legs fixed in build_itinerary.py):
  1. The tool synthesized lossy strategy_sections from tiles instead of reading
     the authoritative ``state["strategy_sections"]`` -- dropping the diving
     ``content_added`` coordinates and bucketing tiles into ``local_expert``
     (which the builder skips for activity extraction).
  2. ``state["tiles"]`` (with the freshly injected specialist tiles) was
     bypassed whenever the LLM supplied a non-default ``tiles_json``.

These tests assert that with a real diving section in state and an LLM-supplied
refresh ``tiles_json``, the builder places real activity blocks with diving
coordinates intact -- not all Free Days.
"""

from __future__ import annotations

import json
from typing import Any, Dict

from app.planner.tools.build_itinerary import (
    _merge_tiles_by_category,
    build_itinerary,
)


def _diving_section() -> Dict[str, Any]:
    """A real-shaped diving strategy section whose content_added items carry
    ``[lng, lat]`` coordinates (the Mapbox convention the builder expects)."""
    return {
        "specialist_type": "diving",
        "feasibility_status": "feasible",
        "subtitle": "Bonaire",
        "content_added": [
            {
                "type": "activity",
                "title": "1000 Steps Shore Dive",
                "description": "Iconic Bonaire shore dive with healthy coral.",
                "duration_hours": 3.0,
                "coordinates": [-68.3, 12.22],  # [lng, lat]
            },
            {
                "type": "activity",
                "title": "Salt Pier Dive",
                "description": "Pillars draped in marine life under the salt pier.",
                "duration_hours": 3.0,
                "coordinates": [-68.28, 12.08],  # [lng, lat]
            },
        ],
        "constraints_applied": [
            {
                "constraint_id": "min_24h_buffer_after_dive",
                "type": "temporal",
                "rule": "min_24h_buffer_after_dive",
                "severity": "blocking",
                "reason": "No flying within 24h of diving.",
            }
        ],
    }


def _bonaire_state() -> Dict[str, Any]:
    """Bonaire-shaped agent state with a diving section plus state tiles that
    include diving specialist tiles AND no-meta Google-shaped activity tiles."""
    return {
        "trip_plan": {
            "destination": "Bonaire",
            "start_date": "2026-07-04",
            "end_date": "2026-07-11",
            "origin": "Miami",
        },
        "strategy_sections": [_diving_section()],
        "tiles": {
            "activities": [
                # Diving specialist tile (would also be injected from the section,
                # but present here mirrors the persisted post-specialist state).
                {
                    "id": "dive_1000_steps",
                    "title": "1000 Steps Shore Dive",
                    "subtitle": "Bonaire",
                    "category": "activity",
                    "source_agent": "vertical_specialist",
                    "meta": {"specialist_type": "diving", "duration_hours": 3.0},
                    "coordinates": [-68.3, 12.22],
                },
                # No-meta Google-shaped tile: top-level category, no
                # meta.specialist_type. The lossy synthesis path would bucket
                # this into "local_expert" and the builder would skip it.
                {
                    "id": "gp_museum",
                    "title": "Terramar Museum",
                    "subtitle": "Kralendijk",
                    "category": "activity",
                    "source": "google_places",
                },
            ],
            "hotels": [],
            "flights": [],
        },
        "constraints": [],
    }


def _is_all_free_days(result: Dict[str, Any]) -> bool:
    """True when every placed block is the generic Free Day placeholder."""
    for card in result.get("day_cards", []):
        for block in card.get("blocks", []):
            title = (block.get("title") or "").lower()
            if "free day" not in title and "explore at your own pace" not in title:
                return False
    return True


async def test_state_sections_place_diving_with_coordinates() -> None:
    """The core bug: with a non-default LLM tiles_json refresh, the builder must
    still read state.strategy_sections + injected diving tiles, placing real
    diving blocks with coordinates -- not collapsing to all Free Days."""
    state = _bonaire_state()

    # LLM-supplied non-default refresh: a fresh activity tile from search_tiles.
    # It CANNOT contain the diving section, so any placed diving coords prove
    # state["strategy_sections"] was read (Leg 1), and the merge kept state
    # tiles authoritative (Leg 2).
    llm_tiles_json = json.dumps(
        {
            "activities": [
                {
                    "id": "gp_cooking_class",
                    "title": "Bonaire Cooking Class",
                    "subtitle": "Kralendijk",
                    "category": "activity",
                    "source": "google_places",
                }
            ]
        }
    )

    result = await build_itinerary.ainvoke(
        {
            "destination": "Bonaire",
            "start_date": "2026-07-04",
            "end_date": "2026-07-11",
            "tiles_json": llm_tiles_json,
            "state": state,
        }
    )

    assert isinstance(result, dict)
    assert result["success"] is True

    # Not all Free Days -- at least one real activity block placed.
    assert result["activities_placed"] >= 1
    assert not _is_all_free_days(result)

    # At least one placed diving block carries non-None coordinates.
    diving_with_coords = False
    for card in result.get("day_cards", []):
        for block in card.get("blocks", []):
            if block.get("specialist_type") == "diving" and block.get("coordinates"):
                coords = block["coordinates"]
                if coords.get("lat") is not None and coords.get("lng") is not None:
                    diving_with_coords = True
    assert diving_with_coords, "expected a placed diving block with coordinates"


def test_merge_tiles_keeps_state_and_adds_fresh_llm_tiles() -> None:
    """Leg 2 guard: the category merge keeps state/specialist tiles (winning on
    id collisions) AND includes genuinely-fresh LLM tiles -- never dropping the
    LLM refresh, never letting a stale LLM copy clobber a specialist tile."""
    state_tiles = {
        "activities": [
            {"id": "dive_1", "title": "State Diving", "source_agent": "vertical_specialist"},
            {"id": "shared", "title": "State Copy"},
        ],
        "hotels": [{"id": "h1", "title": "State Hotel"}],
    }
    llm_tiles = {
        "activities": [
            {"id": "shared", "title": "LLM Copy (should lose)"},
            {"id": "fresh", "title": "Fresh LLM Activity"},
        ],
    }

    merged = _merge_tiles_by_category(state_tiles, llm_tiles)
    acts = {t["id"]: t for t in merged["activities"]}

    # State specialist tile survives.
    assert "dive_1" in acts
    # Genuinely-fresh LLM tile is included (not dropped).
    assert "fresh" in acts
    assert acts["fresh"]["title"] == "Fresh LLM Activity"
    # On id collision, the state copy wins.
    assert acts["shared"]["title"] == "State Copy"
    # State-only category preserved.
    assert merged["hotels"][0]["id"] == "h1"


async def test_merge_never_resurrects_removed_tile() -> None:
    """Removal-inert regression (commit 3de1d34 bug class): the always-merge in
    build_itinerary must NOT resurrect a tile that was removed from the plan.

    Two scenarios in one test, both deterministic (no LLM, no network):

    Scenario A -- removed from BOTH inputs:
      A previously-present "cooking" tile is absent from state["tiles"], from the
      LLM tiles_json refresh, AND from every strategy_section. ``_merge_tiles_by_category``
      is a pure function whose output is provably a subset (by id) of its two
      inputs, so the removed id can never reappear -- and the built itinerary must
      carry no trace of it (id or unique title).

    Scenario B -- converse safety (stale tile only in LLM tiles_json):
      If a stale tile id leaks into the LLM tiles_json but no section/state
      references it, the merge legitimately keeps it (it cannot distinguish a
      genuinely-fresh search result from a stale leak by id alone). The invariant
      we lock is narrower and matches real builder behavior: such a tile is NEVER
      scheduled as a *specialist* activity. It surfaces at most as a generic
      experience block (activity_type="experience", specialist_type=None,
      activity_domain="tier2") via the Phase 5.6 logistics-backfill path -- which
      is the current, observed behavior, asserted here rather than assumed.
    """
    # ── Scenario A: removed from state, LLM, and sections ──────────────────────
    # Pure-function invariant: merged output is a subset (by id) of the inputs.
    state_tiles_a = {
        "activities": [
            {
                "id": "dive_1000_steps",
                "title": "1000 Steps Shore Dive",
                "source_agent": "vertical_specialist",
            },
        ],
        "hotels": [],
    }
    llm_tiles_a = {
        "activities": [
            {"id": "gp_fresh_lookout", "title": "Fresh Scenic Lookout", "source": "google_places"},
        ],
    }
    # The removed "cooking" tile (REMOVED_ID) is in NEITHER input.
    REMOVED_ID = "stale_cooking_class"
    REMOVED_TITLE = "REMOVED Cooking Class"

    merged = _merge_tiles_by_category(state_tiles_a, llm_tiles_a)

    input_ids = {
        t["id"]
        for cat in (state_tiles_a, llm_tiles_a)
        for t in cat.get("activities", [])
        if t.get("id")
    }
    merged_ids = {t["id"] for t in merged["activities"] if t.get("id")}
    # Every id-bearing merged tile is drawn from the two inputs -- nothing invented.
    assert merged_ids <= input_ids
    # The removed tile is absent from the merge.
    assert REMOVED_ID not in merged_ids

    # Build-level "no trace": the removed id/title appear NOWHERE in the result.
    # State, LLM tiles_json, and the diving section all omit the removed tile.
    state = _bonaire_state()
    state["tiles"]["activities"] = [
        t for t in state["tiles"]["activities"] if t["id"] != REMOVED_ID
    ]
    assert all(
        REMOVED_ID not in json.dumps(sec) and REMOVED_TITLE not in json.dumps(sec)
        for sec in state["strategy_sections"]
    ), "fixture sanity: removed tile must not be referenced by any section"

    llm_tiles_json = json.dumps(
        {
            "activities": [
                {
                    "id": "gp_fresh_lookout",
                    "title": "Fresh Scenic Lookout",
                    "type": "activity",
                    "category": "activity",
                    "source": "google_places",
                }
            ]
        }
    )

    result = await build_itinerary.ainvoke(
        {
            "destination": "Bonaire",
            "start_date": "2026-07-04",
            "end_date": "2026-07-11",
            "tiles_json": llm_tiles_json,
            "state": state,
        }
    )
    assert result["success"] is True
    result_blob = json.dumps(result)
    # Unique sentinel id + title -> substring scan cannot false-negative.
    assert REMOVED_ID not in result_blob
    assert REMOVED_TITLE not in result_blob

    # ── Scenario B: stale tile leaks into LLM tiles_json only ──────────────────
    # No section/state references it. The merge keeps it (can't tell stale from
    # fresh by id), but it must never be scheduled as a specialist block.
    state_b = _bonaire_state()  # diving section + diving state tile, no cooking ref
    leaked_llm_json = json.dumps(
        {
            "activities": [
                {
                    "id": REMOVED_ID,
                    "title": REMOVED_TITLE,
                    "subtitle": "Kralendijk",
                    "type": "activity",
                    "category": "activity",
                    "source": "google_places",
                }
            ]
        }
    )

    result_b = await build_itinerary.ainvoke(
        {
            "destination": "Bonaire",
            "start_date": "2026-07-04",
            "end_date": "2026-07-11",
            "tiles_json": leaked_llm_json,
            "state": state_b,
        }
    )
    assert result_b["success"] is True

    # Locate the block carrying the leaked tile (block.id / block.summary).
    leaked_blocks = [
        block
        for card in result_b.get("day_cards", [])
        for block in card.get("blocks", [])
        if block.get("id") == REMOVED_ID or block.get("summary") == REMOVED_TITLE
    ]
    # Invariant: a leaked tile is NEVER promoted to a specialist activity.
    for block in leaked_blocks:
        assert block.get("specialist_type") is None
        assert block.get("specialist_type") != "diving"
    # Observed real behavior: it surfaces as a generic tier2 experience block.
    if leaked_blocks:
        block = leaked_blocks[0]
        assert block.get("activity_type") == "experience"
        assert block.get("activity_domain") == "tier2"

    # The real diving section is unharmed -- its blocks remain specialist diving.
    diving_blocks = [
        block
        for card in result_b.get("day_cards", [])
        for block in card.get("blocks", [])
        if block.get("specialist_type") == "diving"
    ]
    assert len(diving_blocks) >= 1, "diving section must still place specialist blocks"
    # The leaked tile id never appears on any diving block.
    for block in diving_blocks:
        assert block.get("id") != REMOVED_ID
        assert block.get("summary") != REMOVED_TITLE


async def test_one_day_trip_returns_human_readable_error() -> None:
    """Bug 2 (graceful 1-day handling): a sub-2-day trip (start_date ==
    end_date) makes ItineraryBuilder.build() return success=False with the terse
    sentinel ``TRIP_TOO_SHORT``. The tool must surface success=False AND a
    non-empty, human-readable ``error`` that mentions the 2-day minimum -- not
    the raw sentinel -- so the agent loop can explain the problem and the
    TurnLifecycle middleware preserves existing day_cards instead of wiping them.
    """
    state = _bonaire_state()
    state["trip_plan"]["start_date"] = "2026-07-04"
    state["trip_plan"]["end_date"] = "2026-07-04"  # 1-day trip

    result = await build_itinerary.ainvoke(
        {
            "destination": "Bonaire",
            "start_date": "2026-07-04",
            "end_date": "2026-07-04",
            "tiles_json": "{}",
            "state": state,
        }
    )

    assert isinstance(result, dict)
    assert result["success"] is False

    error_msg = result.get("error")
    assert isinstance(error_msg, str) and error_msg.strip(), (
        "1-day trip must surface a non-empty human-readable error"
    )
    # Human-readable, not the raw sentinel.
    assert error_msg != "TRIP_TOO_SHORT"
    assert "TRIP_TOO_SHORT" not in error_msg
    # Mentions the 2-day minimum so the model can guide the user.
    lowered = error_msg.lower()
    assert "2 day" in lowered or "at least 2" in lowered
    assert "extend" in lowered or "at least one day" in lowered

    # Happy-path keys are still present (middleware reads builder metadata).
    for key in ("day_cards", "conflicts", "activities_placed", "activities_dropped"):
        assert key in result


async def test_conflict_with_partial_schedule_is_not_flagged_as_error(monkeypatch) -> None:
    """Bug 2 gate regression: the builder's CONSTRAINT_CONFLICT path returns
    success=False but WITH a populated partial schedule (itinerary_builder ~801).

    The tool must surface an ``error`` ONLY when there are no usable day_cards.
    For a conflict (non-empty day_cards) it must NOT set ``error`` -- otherwise
    TurnLifecycleMiddleware treats it as a tool error and skips _merge_itinerary,
    dropping the partial schedule + conflicts and never computing the
    S3_PARTIAL_CONFLICT view-state.
    """
    from types import SimpleNamespace

    from app.services.itinerary_builder import ItineraryBuilder

    class _FakeCard:
        def __init__(self, day: int) -> None:
            self._day = day

        def model_dump(self) -> Dict[str, Any]:
            return {"day_number": self._day, "blocks": [{"title": "Partial activity"}]}

    class _FakeConflict:
        def model_dump(self) -> Dict[str, Any]:
            return {"code": "ALTITUDE_AFTER_DIVE", "severity": "blocking"}

    fake_result = SimpleNamespace(
        success=False,
        error="CONSTRAINT_CONFLICT",
        day_cards=[_FakeCard(1), _FakeCard(2)],
        conflicts=[_FakeConflict()],
        total_activities_input=2,
        total_activities_placed=2,
        warnings=[],
        overview=None,
        assumptions=None,
    )

    monkeypatch.setattr(ItineraryBuilder, "build", lambda self, input_data: fake_result)

    result = await build_itinerary.ainvoke(
        {
            "destination": "Bonaire",
            "start_date": "2026-07-04",
            "end_date": "2026-07-11",
            "tiles_json": "{}",
            "state": _bonaire_state(),
        }
    )

    assert result["success"] is False
    # Partial schedule + conflicts preserved so the merger can surface them.
    assert len(result["day_cards"]) == 2
    assert len(result["conflicts"]) == 1
    # CRITICAL: no 'error' key -> not treated as a tool error -> still merges.
    assert "error" not in result


async def test_state_only_injection_reaches_tool_body() -> None:
    """Guard test: with tiles_json='{}' and state-only, the injected specialist
    tiles + real sections must still place activities. If this fails, the
    InjectedState mechanism did not reach the tool body (mechanism failure,
    not a logic failure in the fix)."""
    state = _bonaire_state()

    result = await build_itinerary.ainvoke(
        {
            "destination": "Bonaire",
            "start_date": "2026-07-04",
            "end_date": "2026-07-11",
            "tiles_json": "{}",
            "state": state,
        }
    )

    assert isinstance(result, dict)
    assert result["success"] is True
    assert result["activities_placed"] > 0, (
        "state-only invoke placed 0 activities -- InjectedState likely did not reach the tool body"
    )
