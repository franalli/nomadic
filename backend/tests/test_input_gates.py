"""Unit tests for input gates + registry integration."""

from datetime import date, timedelta
from unittest.mock import MagicMock

from app.planner.nodes.input_gate_config import GATE_THRESHOLDS
from app.planner.nodes.input_gates import (
    BudgetGate,
    DateGate,
    DestinationGate,
    DurationGate,
    GateRegistry,
    InputGate,
    TravelerGate,
)


def _make_plan(**overrides):
    plan = MagicMock()
    tomorrow = date.today() + timedelta(days=1)
    plan.start_date = overrides.get("start_date", tomorrow.isoformat())
    plan.end_date = overrides.get("end_date", (tomorrow + timedelta(days=7)).isoformat())
    plan.destination = overrides.get("destination", "Bali")
    plan.adults = overrides.get("adults", 2)
    plan.children = overrides.get("children", 0)
    plan.budget = overrides.get("budget", None)
    plan._multi_dest_from_llm = overrides.get("_multi_dest_from_llm", False)
    plan._deferred_destinations = overrides.get("_deferred_destinations", [])
    return plan


class TestDateGate:
    gate = DateGate()

    def test_no_dates_passes(self):
        plan = _make_plan(start_date=None, end_date=None)
        assert self.gate.evaluate(plan, GATE_THRESHOLDS) is None

    def test_valid_dates_pass(self):
        assert self.gate.evaluate(_make_plan(), GATE_THRESHOLDS) is None

    def test_past_date_blocks(self):
        r = self.gate.evaluate(
            _make_plan(start_date="2020-01-01", end_date="2020-01-10"),
            GATE_THRESHOLDS,
        )
        assert r is not None and r.severity == "blocking" and r.code == "date_in_past"

    def test_end_before_start_blocks(self):
        r = self.gate.evaluate(
            _make_plan(start_date="2026-03-10", end_date="2026-03-01"),
            GATE_THRESHOLDS,
        )
        assert r is not None and r.code == "end_before_start"

    def test_too_far_future_blocks(self):
        far = date.today() + timedelta(days=600)
        r = self.gate.evaluate(
            _make_plan(
                start_date=far.isoformat(),
                end_date=(far + timedelta(5)).isoformat(),
            ),
            GATE_THRESHOLDS,
        )
        assert r is not None and r.code == "too_far_future"


class TestDurationGate:
    gate = DurationGate()

    def test_normal_passes(self):
        assert self.gate.evaluate(_make_plan(), GATE_THRESHOLDS) is None

    def test_long_warns(self):
        t = date.today() + timedelta(days=1)
        r = self.gate.evaluate(
            _make_plan(
                start_date=t.isoformat(),
                end_date=(t + timedelta(35)).isoformat(),
            ),
            GATE_THRESHOLDS,
        )
        assert r is not None and r.severity == "warning" and r.code == "trip_long"

    def test_too_long_blocks(self):
        t = date.today() + timedelta(days=1)
        r = self.gate.evaluate(
            _make_plan(
                start_date=t.isoformat(),
                end_date=(t + timedelta(100)).isoformat(),
            ),
            GATE_THRESHOLDS,
        )
        assert r is not None and r.severity == "blocking" and r.code == "trip_too_long"


class TestTravelerGate:
    gate = TravelerGate()

    def test_normal_passes(self):
        assert self.gate.evaluate(_make_plan(), GATE_THRESHOLDS) is None

    def test_too_many_blocks(self):
        r = self.gate.evaluate(
            _make_plan(adults=20, children=10),
            GATE_THRESHOLDS,
        )
        assert r is not None and r.code == "too_many_travelers"

    def test_children_without_adult(self):
        r = self.gate.evaluate(
            _make_plan(adults=0, children=3),
            GATE_THRESHOLDS,
        )
        assert r is not None and r.code == "children_without_adult"


class TestBudgetGate:
    gate = BudgetGate()

    def test_no_budget_passes(self):
        assert self.gate.evaluate(_make_plan(), GATE_THRESHOLDS) is None

    def test_normal_passes(self):
        assert self.gate.evaluate(_make_plan(budget=5000), GATE_THRESHOLDS) is None

    def test_too_low_blocks(self):
        r = self.gate.evaluate(_make_plan(budget=10), GATE_THRESHOLDS)
        assert r is not None and r.code == "budget_too_low"

    def test_extreme_high_blocks(self):
        r = self.gate.evaluate(_make_plan(budget=1_000_000), GATE_THRESHOLDS)
        assert r is not None and r.code == "budget_extreme"

    def test_high_warns(self):
        r = self.gate.evaluate(_make_plan(budget=150_000), GATE_THRESHOLDS)
        assert r is not None and r.severity == "warning" and r.code == "budget_high"


class TestDestinationGate:
    gate = DestinationGate()

    def test_single_passes(self):
        assert self.gate.evaluate(_make_plan(), GATE_THRESHOLDS) is None

    def test_compound_name_passes(self):
        plan = _make_plan(destination="Trinidad and Tobago")
        assert self.gate.evaluate(plan, GATE_THRESHOLDS) is None
        assert plan.destination == "Trinidad and Tobago"

    def test_turks_and_caicos_passes(self):
        plan = _make_plan(destination="Turks and Caicos")
        assert self.gate.evaluate(plan, GATE_THRESHOLDS) is None

    def test_two_comma_passes(self):
        plan = _make_plan(destination="Washington, DC")
        assert self.gate.evaluate(plan, GATE_THRESHOLDS) is None

    def test_three_comma_splits(self):
        plan = _make_plan(destination="Paris, Tokyo, Bali")
        r = self.gate.evaluate(plan, GATE_THRESHOLDS)
        assert r is not None and r.code == "multi_destination_detected"
        assert plan.destination == "Paris"

    def test_llm_flag_primary(self):
        plan = _make_plan(
            destination="Rome",
            _multi_dest_from_llm=True,
            _deferred_destinations=["Switzerland"],
        )
        r = self.gate.evaluate(plan, GATE_THRESHOLDS)
        assert r is not None and r.code == "multi_destination_detected"
        assert "Switzerland" in r.message


class TestGateRegistry:
    def test_clean_plan_no_violations(self):
        reg = GateRegistry()
        blockers, warnings = reg.run_all(_make_plan())
        assert len(blockers) == 0

    def test_multiple_blockers_detected(self):
        reg = GateRegistry()
        blockers, _ = reg.run_all(
            _make_plan(
                start_date="2020-01-01",
                end_date="2020-01-02",
                adults=0,
                children=5,
            ),
        )
        assert len(blockers) >= 2

    def test_fail_open_on_gate_exception(self):
        class BrokenGate(InputGate):
            def evaluate(self, tp, th):
                raise RuntimeError("boom")

        reg = GateRegistry(gates=[BrokenGate()])
        blockers, warnings = reg.run_all(_make_plan())
        assert len(blockers) == 0 and len(warnings) == 0
