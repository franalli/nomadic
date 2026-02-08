"""
Test Architecture - "Diving in Bali" Scenario.

This test verifies the complete flow:
Router → Specialist → Architect → Guard → Synthesizer

Run with: pytest tests/test_architecture.py -v
"""

import pytest

from app.planner.nodes.intent_router import (
    IntentClassification,
    _detect_specialist_keywords,
)
from app.planner.nodes.synthesizer import Synthesizer, generate_suggestions
from app.planner.nodes.trip_architect import TripArchitect
from app.planner.nodes.vertical_specialist import VerticalSpecialist
from app.planner.state import (
    GraphState,
    SpecialistConstraint,
    TripPlan,
)

# =============================================================================
# Unit Tests
# =============================================================================


class TestIntentRouter:
    """Test the IntentRouter node (LLM-based classification)."""

    def test_detect_diving_specialist(self):
        """Should detect diving keywords via fallback detection."""
        assert "diving" in _detect_specialist_keywords("I want to go diving")
        assert "diving" in _detect_specialist_keywords("scuba trip to Bali")
        assert "diving" in _detect_specialist_keywords("wreck diving in Egypt")
        assert "diving" in _detect_specialist_keywords("padi certification")

    def test_detect_hiking_specialist(self):
        """Should detect hiking keywords."""
        assert "hiking" in _detect_specialist_keywords("hiking in Patagonia")
        assert "hiking" in _detect_specialist_keywords("trekking to Everest")
        assert "hiking" in _detect_specialist_keywords("mountain trails")

    def test_detect_skiing_specialist(self):
        """Should detect skiing keywords."""
        assert "skiing" in _detect_specialist_keywords("skiing in Chamonix")
        assert "skiing" in _detect_specialist_keywords("snowboarding trip")
        assert "skiing" in _detect_specialist_keywords("powder snow Japan")

    def test_no_specialist_for_general(self):
        """Should return empty list for general queries."""
        assert _detect_specialist_keywords("I want to visit Paris") == []
        assert _detect_specialist_keywords("beach vacation") == []

    def test_intent_classification_schema(self):
        """Test IntentClassification schema structure."""
        # Test PLANNING classification with specialist hints
        classification = IntentClassification(
            intent="PLANNING",
            confidence=0.9,
            reasoning="User wants to go diving",
            specialist_hints=["diving"],
        )
        assert classification.intent == "PLANNING"
        assert "diving" in classification.specialist_hints
        assert classification.confidence == 0.9

    def test_intent_classification_greeting(self):
        """Test GREETING classification schema."""
        classification = IntentClassification(
            intent="GREETING",
            confidence=0.95,
            reasoning="Simple greeting with no trip content",
        )
        assert classification.intent == "GREETING"
        assert classification.specialist_hints == []

    def test_intent_classification_reset(self):
        """Test RESET classification schema."""
        classification = IntentClassification(
            intent="RESET",
            confidence=0.85,
            reasoning="User wants to start over",
        )
        assert classification.intent == "RESET"


class TestTripArchitect:
    """Test the TripArchitect node."""

    def test_pre_core_mode_detection(self):
        """Should detect pre-core mode when destination missing."""
        architect = TripArchitect()
        state = GraphState()

        mode = architect.determine_mode(state)
        assert mode == "pre_core"

    def test_missing_fields_mode(self):
        """Should detect missing fields when destination present but dates missing."""
        architect = TripArchitect()
        state = GraphState()
        state.trip_plan.destination = "Bali"

        mode = architect.determine_mode(state)
        assert mode == "missing_fields"

    def test_planning_mode(self):
        """Should be in planning mode when core fields present."""
        architect = TripArchitect()
        state = GraphState()
        state.trip_plan.destination = "Bali"
        state.trip_plan.start_date = "2024-03-15"

        mode = architect.determine_mode(state)
        assert mode == "planning"

    def test_pre_core_response(self):
        """Should generate conversational pre-core response."""
        architect = TripArchitect()
        state = GraphState()

        response = architect.generate_pre_core_response(state, "I want to go somewhere warm")
        assert "beach" in response.lower() or "tropical" in response.lower()


class TestVerticalSpecialist:
    """Test the VerticalSpecialist node."""

    def test_diving_constraints(self):
        """Should return diving-specific constraints."""
        specialist = VerticalSpecialist("diving")
        constraints = specialist.get_constraints()

        # Should have no-fly constraint
        constraint_rules = [c.rule for c in constraints]
        assert "min_24h_buffer_after_dive" in constraint_rules

    @pytest.mark.asyncio
    async def test_specialist_output_structure(self):
        """Should return both constraints and content."""
        specialist = VerticalSpecialist("diving")
        state = GraphState()
        state.trip_plan.destination = "Bali"

        output = await specialist.generate_output(state)

        assert len(output.constraints) > 0
        assert len(output.content_blocks) > 0
        assert output.enhancements  # Should have enhancement suggestions


class TestConstraintGuard:
    """Test the ConstraintGuard node."""

    def test_budget_constraint(self):
        """Should detect budget violations."""
        from app.planner.nodes.constraint_guard import check_budget_constraint

        plan = TripPlan(budget=1000)
        tiles = {
            "hotels": [{"price_estimate": 800}],
            "flights": [{"price_estimate": 600}],
        }

        violations = check_budget_constraint(plan, tiles)
        assert len(violations) > 0
        assert any("BUDGET" in v.code for v in violations)

    def test_date_order_constraint(self):
        """Should detect date order violations."""
        from app.planner.nodes.constraint_guard import check_temporal_constraints

        plan = TripPlan(
            start_date="2024-03-20",
            end_date="2024-03-15",  # End before start!
        )

        violations = check_temporal_constraints(plan, {})
        assert len(violations) > 0
        assert any("DATE_ORDER" in v.code for v in violations)

    def test_specialist_constraint_checking(self):
        """Should detect diving-on-departure-day conflict."""
        from app.planner.nodes.constraint_guard import check_specialist_constraints
        from app.planner.state import ItineraryBlock

        plan = TripPlan(
            destination="Bali",
            start_date="2025-03-01",
            end_date="2025-03-04",  # 4-day trip
        )
        plan.constraints.append(
            SpecialistConstraint(
                type="temporal",
                rule="min_24h_buffer_after_dive",
                applies_to="flights",
            )
        )
        # Diving on day 4 (departure day) = conflict
        plan.itinerary_blocks.append(
            ItineraryBlock(
                day=4,
                title="Morning dive",
                description="Dive at USS Liberty",
                type="activity",
                source_specialist="diving",
            )
        )
        tiles = {"flights": [{"id": "f1", "type": "flight"}]}

        violations = check_specialist_constraints(plan, tiles)
        assert len(violations) > 0
        assert any("DIVING" in v.code for v in violations)


class TestSynthesizer:
    """Test the Synthesizer node."""

    def test_suggested_replies_count(self):
        """Should return up to 3 suggestions."""
        state = GraphState()
        suggestions = generate_suggestions(state)
        assert 1 <= len(suggestions) <= 3

    def test_all_suggestions_are_executable(self):
        """Every suggestion the engine can produce must be routable."""
        import re

        from app.planner.nodes.intent_router import (
            PLANNING_READINESS_SIGNALS,
            QUESTION_TYPE_MAPPING,
            SPECIALIST_PATTERNS,
        )

        def is_routable(text: str) -> bool:
            text_lower = text.lower()
            # Planning readiness signals
            for signal in PLANNING_READINESS_SIGNALS:
                if signal in text_lower:
                    return True
            # Specialist patterns
            for patterns in SPECIALIST_PATTERNS.values():
                for pattern in patterns:
                    if re.search(pattern, text_lower):
                        return True
            # Question type mapping
            for keywords in QUESTION_TYPE_MAPPING:
                if any(kw in text_lower for kw in keywords.split("|")):
                    return True
            # Destination/date/change/origin triggers
            if any(
                kw in text_lower
                for kw in [
                    "beach",
                    "mountain",
                    "city break",
                    "next week",
                    "next month",
                    "flexible",
                    "change",
                    "departure",
                    "set my",
                ]
            ):
                return True
            # Date ranges (e.g., "March 1-8")
            if re.search(r"\b\w+ \d+-\d+", text):
                return True
            return False

        # Test states covering major branches
        test_states = [
            GraphState(),  # No destination
            GraphState(trip_plan=TripPlan(destination="Bali")),  # Has dest, no dates
            GraphState(
                trip_plan=TripPlan(destination="Bali"),
                metadata={"detected_month": "March"},
            ),  # Has dest + detected month
            GraphState(
                trip_plan=TripPlan(
                    destination="Bali", start_date="2025-03-01", end_date="2025-03-08"
                ),
            ),  # Has dest + dates, no specialists
            GraphState(
                trip_plan=TripPlan(
                    destination="Bali", start_date="2025-03-01", end_date="2025-03-08"
                ),
                metadata={"executed_strategy_topics": ["diving"]},
                tiles={"hotels": [{"id": "1"}]},
            ),  # Has tiles, diving done
        ]
        for state in test_states:
            suggestions = generate_suggestions(state)
            for text in suggestions:
                assert is_routable(text), (
                    f"Dead suggestion: '{text}' (state: dest={state.trip_plan.destination}, "
                    f"dates={state.trip_plan.start_date})"
                )

    def test_greeting_response(self):
        """Should generate appropriate greeting."""
        synth = Synthesizer()
        state = GraphState()

        response = synth.synthesize_greeting(state)
        assert "trip" in response.lower() or "adventure" in response.lower()

    def test_planning_response_with_tiles(self):
        """Should mention tiles in planning response."""
        synth = Synthesizer()
        state = GraphState()
        state.trip_plan.destination = "Bali"
        state.tiles = {"hotels": [{"id": "1"}, {"id": "2"}]}

        response = synth.synthesize_planning(state)
        assert "2" in response or "hotel" in response.lower()


# =============================================================================
# Integration Tests
# =============================================================================


# =============================================================================
# Feasibility & Specialist Knowledge Tests (YC Demo Verification)
# =============================================================================


class TestFeasibilityChecks:
    """Test feasibility checking for specialists (Red/Amber/Green card states)."""

    def test_dubai_diving_caveat(self):
        """Dubai should return CAVEAT status for diving (indoor pool recommended)."""
        from app.planner.nodes.vertical_specialist import check_feasibility

        status, reason, alternative = check_feasibility("diving", "Dubai")

        assert status == "caveat", f"Expected 'caveat', got '{status}'"
        assert reason is not None
        assert "Deep Dive Dubai" in reason, f"Should mention Deep Dive Dubai: {reason}"

    def test_landlocked_diving_infeasible(self):
        """Landlocked countries should return INFEASIBLE for diving."""
        from app.planner.nodes.vertical_specialist import check_feasibility

        status, reason, alternative = check_feasibility("diving", "Switzerland")

        assert status == "infeasible", f"Expected 'infeasible', got '{status}'"
        assert alternative is not None  # Should suggest alternative destinations

    def test_bali_diving_feasible(self):
        """Bali should return FEASIBLE for diving (prime destination)."""
        from app.planner.nodes.vertical_specialist import check_feasibility

        status, reason, alternative = check_feasibility("diving", "Bali")

        assert status == "feasible", f"Expected 'feasible', got '{status}'"

    def test_miami_skiing_infeasible(self):
        """Miami should return INFEASIBLE for skiing."""
        from app.planner.nodes.vertical_specialist import check_feasibility

        status, reason, alternative = check_feasibility("skiing", "Miami")

        assert status == "infeasible", f"Expected 'infeasible', got '{status}'"


class TestConstraintFormatting:
    """Test constraint display formatting."""

    def test_diving_constraint_rule_format(self):
        """Diving constraints should use snake_case rules that map to readable titles."""
        from app.planner.nodes.vertical_specialist import VerticalSpecialist

        specialist = VerticalSpecialist("diving")
        constraints = specialist.get_constraints()

        rules = [c.rule for c in constraints]
        assert "min_24h_buffer_after_dive" in rules, "Should have no-fly constraint"

        # This rule should map to "No-Fly Window (24h)" in frontend
        # The mapping is in frontend/components/plan/stages/S2StrategyView.tsx


class TestLocalExpert:
    """Test Local Expert static knowledge and fallback behavior."""

    def test_dubai_local_expert_knowledge(self):
        """Dubai should have static local expert knowledge."""
        from app.planner.nodes.local_expert import _get_static_local_knowledge

        knowledge = _get_static_local_knowledge("Dubai")

        assert len(knowledge.constraints) > 0, "Dubai should have constraints"
        assert len(knowledge.recommendations) > 0, "Dubai should have recommendations"

        # Check for specific Dubai content
        rec_titles = [r.title for r in knowledge.recommendations]
        assert any("Metro" in t for t in rec_titles), f"Should include Dubai Metro: {rec_titles}"

    def test_paris_local_expert_knowledge(self):
        """Paris should have static local expert knowledge."""
        from app.planner.nodes.local_expert import _get_static_local_knowledge

        knowledge = _get_static_local_knowledge("Paris")

        assert len(knowledge.constraints) > 0, "Paris should have constraints"
        assert len(knowledge.recommendations) > 0, "Paris should have recommendations"

        # Check for Louvre closed Tuesday constraint
        constraint_descs = [c.description for c in knowledge.constraints]
        assert any(
            "Louvre" in d and "Tuesday" in d for d in constraint_descs
        ), f"Should mention Louvre closed Tuesday: {constraint_descs}"

    def test_unknown_destination_empty_knowledge(self):
        """Unknown destinations should return empty knowledge."""
        from app.planner.nodes.local_expert import _get_static_local_knowledge

        knowledge = _get_static_local_knowledge("Random Unknown Place XYZ")

        assert len(knowledge.constraints) == 0, "Unknown place should have no constraints"
        assert len(knowledge.recommendations) == 0, "Unknown place should have no recommendations"

    def test_local_expert_logic_hooks(self):
        """Local Expert recommendations should have logic_hooks."""
        from app.planner.nodes.local_expert import _get_static_local_knowledge

        knowledge = _get_static_local_knowledge("Tokyo")

        # All recommendations should have logic_hooks
        for rec in knowledge.recommendations:
            assert rec.logic_hook, f"Recommendation '{rec.title}' missing logic_hook"


# =============================================================================
# Graph Tests
# =============================================================================


class TestGraph:
    """Test the compiled graph."""

    def test_graph_creation(self):
        """Should create graph without errors."""
        from app.plan_graph import create_optimized_graph

        workflow = create_optimized_graph()
        assert workflow is not None

    def test_graph_compilation(self):
        """Should compile graph without errors."""
        from app.plan_graph import get_graph

        graph = get_graph()
        assert graph is not None

    @pytest.mark.asyncio
    async def test_full_graph_execution(self):
        """Should execute full graph flow."""
        from app.plan_graph import get_graph, run_turn_internal

        graph = get_graph()
        result = await run_turn_internal(graph, "I want to go diving in Bali")

        assert result.last_summary  # Has response
        assert result.suggested_replies  # Has suggestions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
