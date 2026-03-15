import importlib.util
import json
from pathlib import Path

_ANALYZER_PATH = Path(__file__).with_name("analyze_flow_logs.py")
_ANALYZER_SPEC = importlib.util.spec_from_file_location("analyze_flow_logs", _ANALYZER_PATH)
assert _ANALYZER_SPEC is not None
assert _ANALYZER_SPEC.loader is not None
analyze_flow_logs = importlib.util.module_from_spec(_ANALYZER_SPEC)
_ANALYZER_SPEC.loader.exec_module(analyze_flow_logs)


def _complete_event(
    destination: str,
    start_date: str,
    end_date: str,
    categories: list[str],
    *,
    include_strategy: bool = True,
) -> str:
    payload = {
        "type": "complete",
        "data": {
            "document": {
                "strategy_sections": [{"id": "strategy_local_expert"}] if include_strategy else [],
            },
            "session_state": {
                "trip_plan": {
                    "destination": destination,
                    "start_date": start_date,
                    "end_date": end_date,
                },
                "trip_settings": {
                    "activity_settings": {
                        "categories": categories,
                        "day_preferences": {},
                        "activities_per_day": 2,
                        "skill_level": None,
                    }
                },
            },
        },
    }
    return f"data: {json.dumps(payload)}"


def test_turn_timing_adds_flow_specific_budget_warning() -> None:
    report = analyze_flow_logs.FlowReport(21, "Long Trip Tile Density — Extend 10 Days")
    backend_log = """
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (initial_plan): extract only (4100 ms)
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (initial_plan): generate plan now (8800 ms)
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (date_change): extend trip (2300 ms)
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (initial_plan): rebuild after extension (19100 ms)
"""

    analyze_flow_logs.check_turn_timing(backend_log, 21, report)

    assert report.metrics["turn_4_time_ms"] == 19100
    assert any("Turn 4 long-trip rebuild took 19100ms" in warning for warning in report.warnings)


def test_turn_timing_does_not_warn_when_exactly_on_budget() -> None:
    report = analyze_flow_logs.FlowReport(19, "Extend Trip — Preserves Day Cards")
    backend_log = """
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (initial_plan): extract only (3900 ms)
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (initial_plan): generate plan now (7400 ms)
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (date_change): extend trip (1800 ms)
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (initial_plan): rebuild after extension (15000 ms)
"""

    analyze_flow_logs.check_turn_timing(backend_log, 19, report)

    assert report.metrics["turn_4_time_ms"] == 15000
    assert not any("post-extension rebuild" in warning for warning in report.warnings)


def test_turn_timing_uses_compact_duration_when_coordinator_log_missing() -> None:
    report = analyze_flow_logs.FlowReport(14, "Full Plan Golden Path — Rome Cultural")
    backend_log = """
⏱️  DURATION        | 4100ms | first turn
⏱️  DURATION        | 22100ms | second turn
"""

    analyze_flow_logs.check_turn_timing(backend_log, 14, report)

    assert report.metrics["turn_2_reason"] == "compact_duration"
    assert report.metrics["turn_2_time_ms"] == 22100
    assert any("Turn 2 full-plan rebuild took 22100ms" in warning for warning in report.warnings)


def test_safe_extension_dispatch_flags_specialist_rerun_from_continuity_log() -> None:
    report = analyze_flow_logs.FlowReport(21, "Long Trip Tile Density — Extend 10 Days")
    backend_log = """
======================================================================
>>> USER INPUT [abc]
======================================================================
please continue with the current trip
----------------------------------------------------------------------
INFO:app.planner.coordinator:[coordinator] Date change continuity: safe_tail_extension=true same_month_bucket=true same_activity_settings=true dispatch=['diving'] preserve=['hiking']
INFO:app.planner.coordinator:[coordinator] Dispatching specialists: ['diving'] (replan=True preserves=['hiking'])
"""

    analyze_flow_logs.check_safe_extension_dispatch(backend_log, "", 21, report)

    assert report.errors == [
        "Turn 1: safe extension dispatched specialists ['diving'] — date extensions should preserve existing specialist plans"
    ]


def test_safe_extension_dispatch_uses_state_when_message_is_not_phrase_match() -> None:
    report = analyze_flow_logs.FlowReport(19, "Extend Trip — Preserves Day Cards")
    backend_log = """
======================================================================
>>> USER INPUT [turn1]
======================================================================
build the trip
----------------------------------------------------------------------
INFO:app.planner.coordinator:[coordinator] Execution plan: PLANNING (initial_plan): generate plan now (steps=2, est_llm=2)
======================================================================
>>> USER INPUT [turn2]
======================================================================
keep the rest the same
----------------------------------------------------------------------
INFO:app.planner.nodes.router_extraction:[CLASSIFIER] change_type=ChangeType.DATE_CHANGE affects=['diving'] preserves=[]
INFO:app.planner.coordinator:[coordinator] Dispatching specialists: ['diving'] (replan=True preserves=[])
"""
    sse_data = "\n".join(
        [
            _complete_event("Bali", "2026-04-01", "2026-04-07", ["diving", "hiking"]),
            _complete_event("Bali", "2026-04-01", "2026-04-17", ["diving", "hiking"]),
        ]
    )

    analyze_flow_logs.check_safe_extension_dispatch(backend_log, sse_data, 19, report)

    assert report.errors == [
        "Turn 2: safe extension dispatched specialists ['diving'] — date extensions should preserve existing specialist plans"
    ]


def test_safe_extension_dispatch_ignores_non_extension_date_change_turn() -> None:
    report = analyze_flow_logs.FlowReport(21, "Long Trip Tile Density — Extend 10 Days")
    backend_log = """
======================================================================
>>> USER INPUT [turn1]
======================================================================
first pass
----------------------------------------------------------------------
INFO:app.planner.coordinator:[coordinator] Execution plan: PLANNING (initial_plan): generate plan now (steps=2, est_llm=2)
======================================================================
>>> USER INPUT [turn2]
======================================================================
move the trip window slightly
----------------------------------------------------------------------
INFO:app.planner.nodes.router_extraction:[CLASSIFIER] change_type=ChangeType.DATE_CHANGE affects=['diving'] preserves=[]
INFO:app.planner.coordinator:[coordinator] Dispatching specialists: ['diving'] (replan=True preserves=[])
"""
    sse_data = "\n".join(
        [
            _complete_event("Bali", "2026-04-01", "2026-04-07", ["diving", "hiking"]),
            _complete_event("Bali", "2026-04-03", "2026-04-17", ["diving", "hiking"]),
        ]
    )

    analyze_flow_logs.check_safe_extension_dispatch(backend_log, sse_data, 21, report)

    assert report.errors == []


def test_analyze_flow_prefers_coordinator_timings_and_detects_state_extension() -> None:
    backend_log = """
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (initial_plan): extract only (4100 ms)
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (initial_plan): generate plan now (8800 ms)
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (add_activity): add hiking (2300 ms)
INFO:app.planner.coordinator:[coordinator] Turn complete: PLANNING (initial_plan): rebuild after extension (19100 ms)
⏱️  DURATION        | 99999ms | noisy fallback that should be ignored
======================================================================
>>> USER INPUT [turn1]
======================================================================
initial
----------------------------------------------------------------------
======================================================================
>>> USER INPUT [turn2]
======================================================================
generate
----------------------------------------------------------------------
======================================================================
>>> USER INPUT [turn3]
======================================================================
add hiking
----------------------------------------------------------------------
======================================================================
>>> USER INPUT [turn4]
======================================================================
keep everything aligned
----------------------------------------------------------------------
INFO:app.planner.nodes.router_extraction:[CLASSIFIER] change_type=ChangeType.DATE_CHANGE affects=['diving'] preserves=[]
INFO:app.planner.coordinator:[coordinator] Dispatching specialists: ['diving'] (replan=True preserves=['hiking'])
"""
    sse_data = "\n".join(
        [
            _complete_event("Bali", "2026-04-01", "2026-04-07", ["diving"]),
            _complete_event("Bali", "2026-04-01", "2026-04-07", ["diving"]),
            _complete_event("Bali", "2026-04-01", "2026-04-07", ["diving", "hiking"]),
            _complete_event("Bali", "2026-04-01", "2026-04-17", ["diving", "hiking"]),
        ]
    )

    report = analyze_flow_logs.analyze_flow(21, backend_log, "", sse_data)

    assert report.metrics["turn_4_reason"] == "PLANNING (initial_plan): rebuild after extension"
    assert report.metrics["turn_4_time_ms"] == 19100
    assert any("Turn 4 long-trip rebuild took 19100ms" in warning for warning in report.warnings)
    assert any("safe extension dispatched specialists" in error for error in report.errors)
