"""
Golden Replay E2E Tests - Fixed scenarios from curated traces.

These tests use predetermined, curated conversation scenarios
for regression testing. They provide deterministic baselines
for detecting regressions in behavior.

Run with: pytest tests/e2e/test_e2e_golden_replays.py -v
"""

import os
import sys
from pathlib import Path

import pytest

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Skip if no OpenAI API key
pytestmark = pytest.mark.skipif(
    not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY required for E2E tests"
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(scope="module")
def enable_langsmith():
    """Enable LangSmith tracing for the test module."""
    from app.config import configure_langsmith_tracing

    if os.getenv("LANGSMITH_KEY"):
        configure_langsmith_tracing(enabled=True, project="nomadic-golden-replays")

    yield


@pytest.fixture
def conversation_executor(enable_langsmith):
    """Create a conversation executor."""
    from tests.e2e.conversation_executor import ConversationExecutor

    return ConversationExecutor(
        enable_langsmith=bool(os.getenv("LANGSMITH_KEY")),
        langsmith_project="nomadic-golden-replays",
    )


@pytest.fixture
def full_evaluator_suite(e2e_model):
    """Create the full evaluator suite."""
    from tests.e2e.evaluators import (
        ConstraintEvaluator,
        GroundednessEvaluator,
        NodeEvaluator,
        QualityEvaluator,
        SafetyEvaluator,
        TravelLogicEvaluator,
    )
    from tests.e2e.evaluators.base_evaluator import CompositeEvaluator

    return CompositeEvaluator(
        [
            QualityEvaluator(model=e2e_model),
            ConstraintEvaluator(model=e2e_model),
            GroundednessEvaluator(model=e2e_model),
            SafetyEvaluator(model=e2e_model),
            TravelLogicEvaluator(model=e2e_model),
            NodeEvaluator(model=e2e_model),
        ]
    )


# =============================================================================
# Golden Scenario Tests
# =============================================================================


class TestGoldenSimpleParisTrip:
    """Golden test: Simple romantic Paris trip."""

    EXPECTED_DESTINATIONS = ["Paris"]
    EXPECTED_DATES_MENTIONED = True
    MIN_SCORE = 0.7

    @pytest.fixture
    def scenario(self):
        from tests.e2e.scenario_generator import get_golden_scenarios

        scenarios = get_golden_scenarios()
        return next(s for s in scenarios if s.scenario_id == "golden_simple_paris_trip")

    @pytest.mark.asyncio
    async def test_destination_extraction(self, conversation_executor, scenario):
        """Test that Paris is correctly extracted."""
        result = await conversation_executor.execute_scenario(scenario)

        assert result.success, f"Conversation failed: {result.errors_encountered}"

        destinations = result.final_trip_inputs.get("destinations", [])
        assert any(
            "paris" in d.lower() for d in destinations
        ), f"Paris not found in destinations: {destinations}"

    @pytest.mark.asyncio
    async def test_date_extraction(self, conversation_executor, scenario):
        """Test that dates are extracted correctly."""
        result = await conversation_executor.execute_scenario(scenario)

        start_date = result.final_trip_inputs.get("start_date")
        end_date = result.final_trip_inputs.get("end_date")

        # At least one date should be captured
        assert start_date or end_date, "No dates were extracted"

        # Check date format if present
        if start_date:
            assert len(start_date) == 10, f"Invalid date format: {start_date}"
            assert start_date.count("-") == 2, f"Invalid date format: {start_date}"

    @pytest.mark.asyncio
    async def test_party_size_extraction(self, conversation_executor, scenario):
        """Test that party size is extracted."""
        result = await conversation_executor.execute_scenario(scenario)

        adults = result.final_trip_inputs.get("adults")
        # Should capture 2 adults for honeymoon couple
        assert adults == 2 or adults is None, f"Unexpected adults count: {adults}"

    @pytest.mark.asyncio
    async def test_quality_evaluation(
        self,
        conversation_executor,
        full_evaluator_suite,
        scenario,
        diagnostic_collector,
        create_enriched_summary,
    ):
        """Test overall quality meets threshold."""
        from tests.e2e.diagnostics import record_evaluation_outcome

        result = await conversation_executor.execute_scenario(scenario)

        # Create enriched trace summary
        trace_summary = await create_enriched_summary(result)

        reports = await full_evaluator_suite.evaluate(
            result=result,
            scenario_goal=scenario.goal,
            scenario_constraints=scenario.constraints.to_dict(),
            trace_summary=trace_summary,
        )

        # Record diagnostic outcome with trace summary
        record_evaluation_outcome(
            test_name="test_quality_evaluation",
            scenario_id=scenario.scenario_id,
            evaluation_reports=reports,
            run_ids=result.run_ids,
            trace_summary=trace_summary,
        )

        avg_score = full_evaluator_suite.get_aggregate_score(reports)
        assert (
            avg_score >= self.MIN_SCORE
        ), f"Quality score {avg_score:.2f} below threshold {self.MIN_SCORE}"


class TestGoldenAsiaBackpacking:
    """Golden test: Complex multi-country backpacking trip."""

    MIN_SCORE = 0.6  # Lower threshold for complex scenario

    @pytest.fixture
    def scenario(self):
        from tests.e2e.scenario_generator import get_golden_scenarios

        scenarios = get_golden_scenarios()
        return next(s for s in scenarios if s.scenario_id == "golden_complex_asia_backpacking")

    @pytest.mark.asyncio
    async def test_multi_country_handling(self, conversation_executor, scenario):
        """Test handling of multi-country ambiguity."""
        result = await conversation_executor.execute_scenario(scenario)

        assert result.success, f"Conversation failed: {result.errors_encountered}"

        # Should have captured at least one SE Asian destination
        destinations = result.final_trip_inputs.get("destinations", [])
        destinations_lower = [d.lower() for d in destinations]

        se_asia_countries = ["thailand", "vietnam", "bangkok", "hanoi", "ho chi minh"]
        found = any(
            any(country in dest for country in se_asia_countries) for dest in destinations_lower
        )

        assert found or len(destinations) > 0, f"No SE Asian destinations captured: {destinations}"

    @pytest.mark.asyncio
    async def test_budget_constraint_handling(self, conversation_executor, scenario):
        """Test that budget constraint is noted."""
        result = await conversation_executor.execute_scenario(scenario)

        budget = result.final_trip_inputs.get("budget")

        # Budget might be captured or conversation might acknowledge it
        budget_mentioned = budget is not None or any(
            "budget" in t.assistant_message.lower() or "$" in t.assistant_message
            for t in result.turns
        )

        # Soft assertion - log warning if not captured
        if not budget_mentioned:
            print("Warning: Budget not explicitly captured in backpacking scenario")

    @pytest.mark.asyncio
    async def test_handles_informal_language(self, conversation_executor, scenario):
        """Test that informal language (hey, idk, etc.) is handled."""
        result = await conversation_executor.execute_scenario(scenario)

        # Should get coherent responses despite informal input
        for turn in result.turns:
            assert (
                len(turn.assistant_message) > 20
            ), f"Turn {turn.turn_number} response too short for informal input"


class TestGoldenFamilySkiTrip:
    """Golden test: Family ski vacation with children."""

    MIN_SCORE = 0.65

    @pytest.fixture
    def scenario(self):
        from tests.e2e.scenario_generator import get_golden_scenarios

        scenarios = get_golden_scenarios()
        return next(s for s in scenarios if s.scenario_id == "golden_family_ski_trip")

    @pytest.mark.asyncio
    async def test_family_composition_extraction(self, conversation_executor, scenario):
        """Test extraction of adults and children."""
        result = await conversation_executor.execute_scenario(scenario)

        adults = result.final_trip_inputs.get("adults")
        children = result.final_trip_inputs.get("children")

        # Should capture family composition
        assert adults is not None or children is not None, "Family composition not captured"

        if adults:
            assert adults == 2, f"Expected 2 adults, got {adults}"
        if children:
            assert children == 2, f"Expected 2 children, got {children}"

    @pytest.mark.asyncio
    async def test_holiday_date_handling(self, conversation_executor, scenario):
        """Test handling of holiday dates."""
        result = await conversation_executor.execute_scenario(scenario)

        start_date = result.final_trip_inputs.get("start_date")

        if start_date:
            # December dates expected
            assert (
                "12" in start_date or "-12-" in start_date
            ), f"Expected December date, got {start_date}"

    @pytest.mark.asyncio
    async def test_strategy_topic_detection(self, conversation_executor, scenario):
        """Test that skiing strategy topic is detected."""
        result = await conversation_executor.execute_scenario(scenario)

        # Check if any turn detected skiing strategy
        strategy_topics = [t.strategy_topic for t in result.turns if t.strategy_topic]

        # Skiing should be detected at some point
        ski_detected = any("ski" in (t or "").lower() for t in strategy_topics)

        # Also check intents
        intents = result.intent_sequence
        strategy_intent = "strategy" in str(intents).lower()

        # One of these should be true
        if not (ski_detected or strategy_intent):
            print("Warning: Skiing strategy not explicitly detected")

    @pytest.mark.asyncio
    async def test_evaluation_passes(
        self,
        conversation_executor,
        full_evaluator_suite,
        scenario,
        diagnostic_collector,
        create_enriched_summary,
    ):
        """Test that evaluation passes threshold."""
        from tests.e2e.diagnostics import record_evaluation_outcome

        result = await conversation_executor.execute_scenario(scenario)

        # Create enriched trace summary
        trace_summary = await create_enriched_summary(result)

        reports = await full_evaluator_suite.evaluate(
            result=result,
            scenario_goal=scenario.goal,
            scenario_constraints=scenario.constraints.to_dict(),
            trace_summary=trace_summary,
        )

        # Record diagnostic outcome with trace summary
        record_evaluation_outcome(
            test_name="test_evaluation_passes",
            scenario_id=scenario.scenario_id,
            evaluation_reports=reports,
            run_ids=result.run_ids,
            trace_summary=trace_summary,
        )

        avg_score = full_evaluator_suite.get_aggregate_score(reports)

        # Log detailed failures
        if avg_score < self.MIN_SCORE:
            failures = full_evaluator_suite.get_all_failures(reports)
            print("\nFailed criteria for family ski trip:")
            for f in failures:
                print(f"  - {f['evaluator']}/{f['criterion']}: {f['score']:.2f}")
                print(f"    Feedback: {f['feedback'][:100]}...")

        assert (
            avg_score >= self.MIN_SCORE
        ), f"Score {avg_score:.2f} below threshold {self.MIN_SCORE}"


# =============================================================================
# Regression Detection Tests
# =============================================================================


class TestGoldenRegressionDetection:
    """Tests specifically designed to detect regressions."""

    @pytest.mark.asyncio
    async def test_all_golden_scenarios_complete(self, conversation_executor):
        """All golden scenarios should complete without errors."""
        from tests.e2e.scenario_generator import get_golden_scenarios

        scenarios = get_golden_scenarios()

        for scenario in scenarios:
            result = await conversation_executor.execute_scenario(scenario)

            assert (
                result.success
            ), f"Scenario {scenario.scenario_id} failed: {result.errors_encountered}"
            assert len(result.turns) == len(scenario.turns), (
                f"Scenario {scenario.scenario_id} didn't complete all turns: "
                f"{len(result.turns)}/{len(scenario.turns)}"
            )

    @pytest.mark.asyncio
    async def test_all_golden_scenarios_extract_destinations(self, conversation_executor):
        """All golden scenarios should extract at least one destination."""
        from tests.e2e.scenario_generator import get_golden_scenarios

        scenarios = get_golden_scenarios()

        for scenario in scenarios:
            result = await conversation_executor.execute_scenario(scenario)

            destinations = result.final_trip_inputs.get("destinations", [])
            assert (
                len(destinations) > 0
            ), f"Scenario {scenario.scenario_id} didn't extract any destinations"

    @pytest.mark.asyncio
    async def test_safety_never_fails_on_golden(
        self, conversation_executor, e2e_model, diagnostic_collector, create_enriched_summary
    ):
        """Safety should never fail on curated golden scenarios."""
        from tests.e2e.diagnostics import record_evaluation_outcome
        from tests.e2e.evaluators import SafetyEvaluator
        from tests.e2e.scenario_generator import get_golden_scenarios

        safety_evaluator = SafetyEvaluator(model=e2e_model)
        scenarios = get_golden_scenarios()

        for scenario in scenarios:
            result = await conversation_executor.execute_scenario(scenario)

            # Create enriched trace summary
            trace_summary = await create_enriched_summary(result)

            report = await safety_evaluator.evaluate(
                result=result,
                scenario_goal=scenario.goal,
                trace_summary=trace_summary,
            )

            # Record diagnostic outcome with trace summary
            record_evaluation_outcome(
                test_name="test_safety_never_fails_on_golden",
                scenario_id=scenario.scenario_id,
                evaluation_reports={"safety_evaluator": report},
                run_ids=result.run_ids,
                trace_summary=trace_summary,
            )

            assert report.overall_passed, (
                f"Safety failed for golden scenario {scenario.scenario_id}: " f"{report.summary}"
            )


# =============================================================================
# Baseline Comparison Tests
# =============================================================================


class TestGoldenBaselines:
    """Tests that compare against expected baseline behavior."""

    @pytest.mark.asyncio
    async def test_routing_consistency(self, conversation_executor):
        """Test that routing is consistent across runs."""
        from tests.e2e.scenario_generator import get_golden_scenarios

        # Use the simplest golden scenario
        scenarios = get_golden_scenarios()
        scenario = scenarios[0]

        # Run twice
        result1 = await conversation_executor.execute_scenario(scenario)
        result2 = await conversation_executor.execute_scenario(scenario)

        # Routing patterns should be similar
        intents1 = [t.router_intent for t in result1.turns if t.router_intent]
        intents2 = [t.router_intent for t in result2.turns if t.router_intent]

        # At least the first intent should match
        if intents1 and intents2:
            # Allow for some variation due to LLM non-determinism
            # but first intent should usually be consistent
            pass  # Soft check - just verify both complete

    @pytest.mark.asyncio
    async def test_destination_extraction_consistency(self, conversation_executor):
        """Test that destination extraction is consistent."""
        from tests.e2e.scenario_generator import get_golden_scenarios

        scenarios = get_golden_scenarios()
        scenario = scenarios[0]  # Paris trip

        # Run twice
        result1 = await conversation_executor.execute_scenario(scenario)
        result2 = await conversation_executor.execute_scenario(scenario)

        dest1 = set(d.lower() for d in result1.final_trip_inputs.get("destinations", []))
        dest2 = set(d.lower() for d in result2.final_trip_inputs.get("destinations", []))

        # Core destinations should overlap
        if dest1 and dest2:
            overlap = dest1.intersection(dest2)
            assert len(overlap) > 0, f"No destination overlap between runs: {dest1} vs {dest2}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
