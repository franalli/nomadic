"""
Test V2 Architecture - "Diving in Bali" Scenario.

This test verifies the complete flow:
Router → Specialist → Architect → Guard → Synthesizer

Run with: pytest tests/test_v2_architecture.py -v
"""

import pytest

from app.planner.nodes_v2.intent_router import (
    IntentClassification,
    _detect_specialist_keyword,
)
from app.planner.nodes_v2.synthesizer import Synthesizer, generate_suggested_replies
from app.planner.nodes_v2.trip_architect import TripArchitect
from app.planner.nodes_v2.vertical_specialist import VerticalSpecialist

# Import V2 components
from app.planner.state import (
    GraphStateV2,
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
        assert _detect_specialist_keyword("I want to go diving") == "diving"
        assert _detect_specialist_keyword("scuba trip to Bali") == "diving"
        assert _detect_specialist_keyword("wreck diving in Egypt") == "diving"
        assert _detect_specialist_keyword("padi certification") == "diving"

    def test_detect_hiking_specialist(self):
        """Should detect hiking keywords."""
        assert _detect_specialist_keyword("hiking in Patagonia") == "hiking"
        assert _detect_specialist_keyword("trekking to Everest") == "hiking"
        assert _detect_specialist_keyword("mountain trails") == "hiking"

    def test_detect_skiing_specialist(self):
        """Should detect skiing keywords."""
        assert _detect_specialist_keyword("skiing in Chamonix") == "skiing"
        assert _detect_specialist_keyword("snowboarding trip") == "skiing"
        assert _detect_specialist_keyword("powder snow Japan") == "skiing"

    def test_no_specialist_for_general(self):
        """Should return None for general queries."""
        assert _detect_specialist_keyword("I want to visit Paris") is None
        assert _detect_specialist_keyword("beach vacation") is None

    def test_intent_classification_schema(self):
        """Test IntentClassification schema structure."""
        # Test PLANNING classification with specialist hint
        classification = IntentClassification(
            intent="PLANNING",
            confidence=0.9,
            reasoning="User wants to go diving",
            specialist_hint="diving",
        )
        assert classification.intent == "PLANNING"
        assert classification.specialist_hint == "diving"
        assert classification.confidence == 0.9

    def test_intent_classification_greeting(self):
        """Test GREETING classification schema."""
        classification = IntentClassification(
            intent="GREETING",
            confidence=0.95,
            reasoning="Simple greeting with no trip content",
        )
        assert classification.intent == "GREETING"
        assert classification.specialist_hint is None

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
        state = GraphStateV2()

        mode = architect.determine_mode(state)
        assert mode == "pre_core"

    def test_missing_fields_mode(self):
        """Should detect missing fields when destination present but dates missing."""
        architect = TripArchitect()
        state = GraphStateV2()
        state.trip_plan.destination = "Bali"

        mode = architect.determine_mode(state)
        assert mode == "missing_fields"

    def test_planning_mode(self):
        """Should be in planning mode when core fields present."""
        architect = TripArchitect()
        state = GraphStateV2()
        state.trip_plan.destination = "Bali"
        state.trip_plan.start_date = "2024-03-15"

        mode = architect.determine_mode(state)
        assert mode == "planning"

    def test_pre_core_response(self):
        """Should generate conversational pre-core response."""
        architect = TripArchitect()
        state = GraphStateV2()

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

    def test_diving_content_for_bali(self):
        """Should return Bali diving content."""
        specialist = VerticalSpecialist("diving")
        blocks = specialist.get_content_for_destination("Bali")

        assert len(blocks) > 0
        block_titles = [b.title for b in blocks]
        assert any("Liberty" in t or "Manta" in t for t in block_titles)

    def test_specialist_output_structure(self):
        """Should return both constraints and content."""
        specialist = VerticalSpecialist("diving")
        state = GraphStateV2()
        state.trip_plan.destination = "Bali"

        output = specialist.generate_output(state)

        assert len(output.constraints) > 0
        assert len(output.content_blocks) > 0
        assert output.enhancements  # Should have enhancement suggestions


class TestConstraintGuard:
    """Test the ConstraintGuard node."""

    def test_budget_constraint(self):
        """Should detect budget violations."""
        from app.planner.nodes_v2.constraint_guard import check_budget_constraint

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
        from app.planner.nodes_v2.constraint_guard import check_temporal_constraints

        plan = TripPlan(
            start_date="2024-03-20",
            end_date="2024-03-15",  # End before start!
        )

        violations = check_temporal_constraints(plan, {})
        assert len(violations) > 0
        assert any("DATE_ORDER" in v.code for v in violations)

    def test_specialist_constraint_checking(self):
        """Should check specialist constraints."""
        from app.planner.nodes_v2.constraint_guard import check_specialist_constraints

        plan = TripPlan()
        plan.constraints.append(
            SpecialistConstraint(
                type="temporal",
                rule="min_24h_buffer_after_dive",
                applies_to="flights",
            )
        )

        violations = check_specialist_constraints(plan, {})
        assert len(violations) > 0
        assert any("DIVING" in v.code for v in violations)


class TestSynthesizer:
    """Test the Synthesizer node."""

    def test_suggested_replies_count(self):
        """Should always return exactly 3 suggestions."""
        state = GraphStateV2()
        suggestions = generate_suggested_replies(state)
        assert len(suggestions) == 3

    def test_greeting_response(self):
        """Should generate appropriate greeting."""
        synth = Synthesizer()
        state = GraphStateV2()

        response = synth.synthesize_greeting(state)
        assert "trip" in response.lower() or "adventure" in response.lower()

    def test_planning_response_with_tiles(self):
        """Should mention tiles in planning response."""
        synth = Synthesizer()
        state = GraphStateV2()
        state.trip_plan.destination = "Bali"
        state.tiles = {"hotels": [{"id": "1"}, {"id": "2"}]}

        response = synth.synthesize_planning(state)
        assert "2" in response or "hotel" in response.lower()


# =============================================================================
# Integration Tests
# =============================================================================


class TestV2Integration:
    """Integration tests for the full V2 flow."""

    @pytest.mark.asyncio
    async def test_diving_bali_flow(self):
        """
        Test the complete "diving in Bali" flow:
        Router → Specialist → Architect → Guard → Synthesizer
        """
        from langchain_core.messages import HumanMessage

        from app.planner.nodes_v2.constraint_guard import constraint_guard
        from app.planner.nodes_v2.intent_router import intent_router
        from app.planner.nodes_v2.synthesizer import synthesizer
        from app.planner.nodes_v2.trip_architect import trip_architect
        from app.planner.nodes_v2.vertical_specialist import vertical_specialist

        # Initialize state
        state = GraphStateV2()
        state.messages.append(HumanMessage(content="I want to go diving in Bali next month"))

        # Step 1: Router (LLM-based, sets active_specialist for diving)
        state = await intent_router(state)
        assert state.active_specialist == "diving"
        assert state.intent == "general"  # LLM router uses "general" for PLANNING

        # Step 2: Specialist
        state = await vertical_specialist(state)
        assert len(state.trip_plan.constraints) > 0  # Diving constraints injected
        assert len(state.trip_plan.itinerary_blocks) > 0  # Content added

        # Manually set trip plan for architect (simulating extraction)
        state.trip_plan.destination = "Bali"
        state.trip_plan.start_date = "2024-04-01"
        state.trip_plan.end_date = "2024-04-08"

        # Step 3: Architect
        state = await trip_architect(state)
        assert state.trip_plan.status == "planning"

        # Step 4: Guard
        state = await constraint_guard(state)
        # Should have diving constraint info
        assert "constraint_violations" in state.metadata

        # Step 5: Synthesizer
        state = await synthesizer(state)
        assert state.last_summary  # Should have response
        assert len(state.suggested_replies) == 3  # Exactly 3 suggestions

        # Verify specialist content is integrated
        assert state.trip_plan.itinerary_blocks
        assert any(
            "diving" in b.source_specialist or ""
            for b in state.trip_plan.itinerary_blocks
            if b.source_specialist
        )

    @pytest.mark.asyncio
    async def test_pre_core_inspiration_flow(self):
        """Test the pre-core inspiration flow for vague requests."""
        from langchain_core.messages import HumanMessage

        from app.planner.nodes_v2.intent_router import intent_router
        from app.planner.nodes_v2.synthesizer import synthesizer
        from app.planner.nodes_v2.trip_architect import trip_architect

        state = GraphStateV2()
        state.messages.append(HumanMessage(content="I want to go somewhere warm"))

        # Router (no specialist detected)
        state = await intent_router(state)
        assert state.active_specialist is None
        assert state.intent == "general"

        # Architect (should be in pre-core mode)
        state = await trip_architect(state)
        assert state.metadata.get("architect_mode") == "pre_core"
        assert state.last_summary  # Should have inspiration response

        # Synthesizer
        state = await synthesizer(state)
        assert state.suggested_replies
        # Should suggest destination types
        suggestions_text = " ".join(state.suggested_replies).lower()
        assert any(
            word in suggestions_text for word in ["beach", "mountain", "city", "destination"]
        )


# =============================================================================
# Graph Tests
# =============================================================================


class TestV2Graph:
    """Test the compiled V2 graph."""

    def test_graph_creation(self):
        """Should create graph without errors."""
        from app.plan_graph_v2 import create_optimized_graph

        workflow = create_optimized_graph()
        assert workflow is not None

    def test_graph_compilation(self):
        """Should compile graph without errors."""
        from app.plan_graph_v2 import get_v2_graph

        graph = get_v2_graph()
        assert graph is not None

    @pytest.mark.asyncio
    async def test_full_graph_execution(self):
        """Should execute full graph flow."""
        from app.plan_graph_v2 import get_v2_graph, run_turn_v2

        graph = get_v2_graph()
        result = await run_turn_v2(graph, "I want to go diving in Bali")

        assert result.last_summary  # Has response
        assert result.suggested_replies  # Has suggestions


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
