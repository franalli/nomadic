"""
PR Gate E2E Tests - Fast subset for pull request validation.

These tests run a small set of fixed scenarios to validate that core
conversation functionality works correctly. They should complete quickly
and are designed to catch regressions in critical paths.

Run with: pytest tests/e2e/test_e2e_pr_gate.py -v
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

    # Only enable if API key is available
    if os.getenv("LANGSMITH_KEY"):
        configure_langsmith_tracing(enabled=True, project="nomadic-pr-gate-tests")

    yield


@pytest.fixture
def conversation_executor(enable_langsmith):
    """Create a conversation executor."""
    from tests.e2e.conversation_executor import ConversationExecutor

    return ConversationExecutor(
        enable_langsmith=bool(os.getenv("LANGSMITH_KEY")),
        langsmith_project="nomadic-pr-gate-tests",
    )


@pytest.fixture
def evaluators():
    """Create the evaluator suite."""
    from tests.e2e.conftest import E2E_MODEL
    from tests.e2e.evaluators import (
        ConstraintEvaluator,
        NodeEvaluator,
        QualityEvaluator,
        SafetyEvaluator,
    )
    from tests.e2e.evaluators.base_evaluator import CompositeEvaluator

    return CompositeEvaluator(
        [
            QualityEvaluator(model=E2E_MODEL),
            ConstraintEvaluator(model=E2E_MODEL),
            SafetyEvaluator(model=E2E_MODEL),
            NodeEvaluator(model=E2E_MODEL),
        ]
    )


# =============================================================================
# Fast Scenario Definitions
# =============================================================================


def get_pr_gate_scenarios():
    """Get a minimal set of scenarios for PR gate testing."""
    from tests.e2e.scenario_generator import (
        ConversationScenario,
        ConversationTurn,
        DifficultySettings,
        ScenarioConstraints,
        UserProfile,
    )

    return [
        # Scenario 1: Simple destination extraction
        ConversationScenario(
            scenario_id="pr_gate_simple_destination",
            user_profile=UserProfile(
                persona="solo_explorer",
                experience_level="intermediate",
                communication_style="casual",
                decision_making="decisive",
            ),
            goal="Plan a trip to Paris",
            constraints=ScenarioConstraints(
                budget="$3000",
                dates="June 2030",
            ),
            difficulty=DifficultySettings(
                level="easy",
                ambiguity_level="none",
            ),
            turns=[
                ConversationTurn(1, "I want to go to Paris next June"),
                ConversationTurn(2, "It'll be just me, budget around $3000"),
                ConversationTurn(3, "I'm flying from New York"),
            ],
        ),
        # Scenario 2: Multi-destination handling
        ConversationScenario(
            scenario_id="pr_gate_multi_destination",
            user_profile=UserProfile(
                persona="adventure_seeker",
                experience_level="expert",
                communication_style="terse",
                decision_making="decisive",
            ),
            goal="Plan a trip to multiple cities in Italy",
            constraints=ScenarioConstraints(
                dates="September 10-24, 2030",
            ),
            difficulty=DifficultySettings(
                level="medium",
                ambiguity_level="low",
            ),
            turns=[
                ConversationTurn(1, "Planning Italy trip: Rome, Florence, Venice"),
                ConversationTurn(2, "Sept 10-24, 2030"),
                ConversationTurn(3, "2 adults from Chicago"),
            ],
        ),
        # Scenario 3: Date parsing edge case
        ConversationScenario(
            scenario_id="pr_gate_date_parsing",
            user_profile=UserProfile(
                persona="family_vacation",
                experience_level="novice",
                communication_style="verbose",
                decision_making="detail_oriented",
            ),
            goal="Plan a family vacation with relative dates",
            constraints=ScenarioConstraints(
                party_size="2 adults, 2 children",
            ),
            difficulty=DifficultySettings(
                level="medium",
                ambiguity_level="medium",
                edge_cases=["relative_dates"],
            ),
            turns=[
                ConversationTurn(1, "We want to take the kids to Disney World"),
                ConversationTurn(2, "Thinking maybe next spring break, about a week"),
                ConversationTurn(
                    3, "There's 4 of us - me, my spouse, and our 2 kids aged 8 and 11"
                ),
                ConversationTurn(4, "We're coming from Boston"),
            ],
        ),
    ]


# =============================================================================
# Tests
# =============================================================================


class TestPRGateBasicFunctionality:
    """Basic functionality tests that must pass for every PR."""

    @pytest.mark.asyncio
    async def test_simple_destination_extraction(self, conversation_executor):
        """Test that simple destinations are extracted correctly."""
        scenarios = get_pr_gate_scenarios()
        scenario = scenarios[0]  # Simple Paris trip

        result = await conversation_executor.execute_scenario(scenario)

        # Basic assertions
        assert result.success, f"Conversation failed: {result.errors_encountered}"
        assert len(result.turns) == len(scenario.turns)

        # Check destination extraction
        final_inputs = result.final_trip_inputs
        assert "Paris" in str(final_inputs.get("destinations", []))

    @pytest.mark.asyncio
    async def test_multi_destination_handling(self, conversation_executor):
        """Test that multiple destinations are handled correctly."""
        scenarios = get_pr_gate_scenarios()
        scenario = scenarios[1]  # Italy multi-city

        result = await conversation_executor.execute_scenario(scenario)

        assert result.success, f"Conversation failed: {result.errors_encountered}"

        # Check multiple destinations extracted
        destinations = result.final_trip_inputs.get("destinations", [])
        destinations_str = str(destinations).lower()

        # At least some Italian cities should be captured
        italian_cities = ["rome", "florence", "venice"]
        found = sum(1 for city in italian_cities if city in destinations_str)
        assert found >= 2, f"Expected at least 2 Italian cities, got: {destinations}"

    @pytest.mark.asyncio
    async def test_conversation_produces_responses(self, conversation_executor):
        """Test that the assistant produces non-empty responses."""
        scenarios = get_pr_gate_scenarios()
        scenario = scenarios[0]

        result = await conversation_executor.execute_scenario(scenario)

        # Every turn should have an assistant response
        for turn in result.turns:
            assert turn.assistant_message, f"Turn {turn.turn_number} has no response"
            assert len(turn.assistant_message) > 10, "Response too short"


class TestPRGateEvaluation:
    """Evaluation tests using LLM judges."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_golden_scenario_quality(
        self, conversation_executor, evaluators, diagnostic_collector, create_enriched_summary
    ):
        """Test that golden scenarios pass quality evaluation."""
        from tests.e2e.diagnostics import record_evaluation_outcome
        from tests.e2e.scenario_generator import get_golden_scenarios

        # Use just the first golden scenario for PR gate (speed)
        scenarios = get_golden_scenarios()[:1]

        for scenario in scenarios:
            result = await conversation_executor.execute_scenario(scenario)

            # Create enriched trace summary for evaluation
            trace_summary = await create_enriched_summary(result)

            # Evaluate with trace summary
            reports = await evaluators.evaluate(
                result=result,
                scenario_goal=scenario.goal,
                scenario_constraints=scenario.constraints.to_dict(),
                trace_summary=trace_summary,
            )

            # Record diagnostic outcome with trace summary
            record_evaluation_outcome(
                test_name="test_golden_scenario_quality",
                scenario_id=scenario.scenario_id,
                evaluation_reports=reports,
                run_ids=result.run_ids,
                trace_summary=trace_summary,
            )

            # Check aggregate score
            avg_score = evaluators.get_aggregate_score(reports)
            assert avg_score >= 0.6, (
                f"Scenario {scenario.scenario_id} scored {avg_score:.2f}, "
                f"failures: {evaluators.get_all_failures(reports)}"
            )

    @pytest.mark.asyncio
    async def test_safety_never_fails(
        self, conversation_executor, diagnostic_collector, create_enriched_summary
    ):
        """Test that safety evaluator never fails on normal inputs."""
        from tests.e2e.conftest import E2E_MODEL
        from tests.e2e.diagnostics import record_evaluation_outcome
        from tests.e2e.evaluators import SafetyEvaluator

        safety_evaluator = SafetyEvaluator(model=E2E_MODEL)

        scenarios = get_pr_gate_scenarios()
        scenario = scenarios[0]

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
            test_name="test_safety_never_fails",
            scenario_id=scenario.scenario_id,
            evaluation_reports={"safety_evaluator": report},
            run_ids=result.run_ids,
            trace_summary=trace_summary,
        )

        assert report.overall_passed, f"Safety evaluation failed: {report.summary}"


class TestPRGateNodeBehavior:
    """Tests for node-level behavior."""

    @pytest.mark.asyncio
    async def test_routing_decisions_logged(self, conversation_executor):
        """Test that routing decisions are captured in metadata."""
        scenarios = get_pr_gate_scenarios()
        scenario = scenarios[0]

        result = await conversation_executor.execute_scenario(scenario)

        # At least some turns should have routing info
        intents = [t.router_intent for t in result.turns if t.router_intent]
        assert len(intents) > 0, "No routing decisions captured"

    @pytest.mark.asyncio
    async def test_no_state_regression(self, conversation_executor):
        """Test that state doesn't unexpectedly regress between turns."""
        scenarios = get_pr_gate_scenarios()
        scenario = scenarios[1]  # Multi-destination

        result = await conversation_executor.execute_scenario(scenario)

        # Track destination count - should never decrease (unless explicit reset)
        max_destinations = 0
        for turn in result.turns:
            destinations = turn.trip_inputs.get("destinations", [])
            current_count = len(destinations)

            # Allow staying same or increasing
            assert current_count >= max_destinations or current_count == 0, (
                f"Destination count regressed at turn {turn.turn_number}: "
                f"{max_destinations} -> {current_count}"
            )
            max_destinations = max(max_destinations, current_count)


# =============================================================================
# CI Integration
# =============================================================================


@pytest.fixture(scope="session", autouse=True)
def report_summary(request):
    """Print summary at end of test session."""
    yield

    # This will be called after all tests complete
    terminal_reporter = request.config.pluginmanager.get_plugin("terminalreporter")
    if terminal_reporter:
        passed = len(terminal_reporter.stats.get("passed", []))
        failed = len(terminal_reporter.stats.get("failed", []))

        print(f"\n{'='*60}")
        print(f"PR Gate E2E Summary: {passed} passed, {failed} failed")
        print(f"{'='*60}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
