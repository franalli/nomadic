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

    @pytest.mark.asyncio
    async def test_dubai_diving_flow_with_caveat(self):
        """
        Test Dubai diving flow returns caveat status and Deep Dive Dubai.
        (YC Demo: Verify specialist knowledge for indoor diving)
        """
        from langchain_core.messages import HumanMessage

        from app.planner.nodes_v2.intent_router import intent_router
        from app.planner.nodes_v2.vertical_specialist import vertical_specialist

        state = GraphStateV2()
        state.messages.append(HumanMessage(content="I want to go diving in Dubai"))
        state.trip_plan.destination = "Dubai"

        # Router should detect diving
        state = await intent_router(state)
        assert state.active_specialist == "diving"

        # Specialist should return caveat status
        state = await vertical_specialist(state)

        # Verify caveat status in metadata
        specialist_output = state.metadata.get("specialist_output", {})
        assert (
            specialist_output.get("feasibility_status") == "caveat"
        ), f"Expected 'caveat', got: {specialist_output.get('feasibility_status')}"
        assert "Deep Dive Dubai" in (
            specialist_output.get("feasibility_reason") or ""
        ), f"Should mention Deep Dive Dubai: {specialist_output.get('feasibility_reason')}"

        # Verify content blocks include Dubai recommendations
        block_titles = [b.title for b in state.trip_plan.itinerary_blocks]
        assert any(
            "Deep Dive Dubai" in t for t in block_titles
        ), f"Should include Deep Dive Dubai in content: {block_titles}"

    @pytest.mark.asyncio
    async def test_infeasible_skiing_in_miami(self):
        """
        Test skiing in Miami returns infeasible status.
        (YC Demo: Red card state for impossible activities)
        """
        from langchain_core.messages import HumanMessage

        from app.planner.nodes_v2.intent_router import intent_router
        from app.planner.nodes_v2.vertical_specialist import vertical_specialist

        state = GraphStateV2()
        state.messages.append(HumanMessage(content="I want to go skiing in Miami"))
        state.trip_plan.destination = "Miami"

        # Router should detect skiing
        state = await intent_router(state)
        assert state.active_specialist == "skiing"

        # Specialist should return infeasible status
        state = await vertical_specialist(state)

        specialist_output = state.metadata.get("specialist_output", {})
        assert (
            specialist_output.get("feasibility_status") == "infeasible"
        ), f"Expected 'infeasible', got: {specialist_output.get('feasibility_status')}"

        # Should have alternative suggestion
        assert specialist_output.get("alternative_suggestion") is not None


# =============================================================================
# Feasibility & Specialist Knowledge Tests (YC Demo Verification)
# =============================================================================


class TestFeasibilityChecks:
    """Test feasibility checking for specialists (Red/Amber/Green card states)."""

    def test_dubai_diving_caveat(self):
        """Dubai should return CAVEAT status for diving (indoor pool recommended)."""
        from app.planner.nodes_v2.vertical_specialist import check_feasibility

        status, reason, alternative = check_feasibility("diving", "Dubai")

        assert status == "caveat", f"Expected 'caveat', got '{status}'"
        assert reason is not None
        assert "Deep Dive Dubai" in reason, f"Should mention Deep Dive Dubai: {reason}"

    def test_landlocked_diving_infeasible(self):
        """Landlocked countries should return INFEASIBLE for diving."""
        from app.planner.nodes_v2.vertical_specialist import check_feasibility

        status, reason, alternative = check_feasibility("diving", "Switzerland")

        assert status == "infeasible", f"Expected 'infeasible', got '{status}'"
        assert alternative is not None  # Should suggest alternative destinations

    def test_bali_diving_feasible(self):
        """Bali should return FEASIBLE for diving (prime destination)."""
        from app.planner.nodes_v2.vertical_specialist import check_feasibility

        status, reason, alternative = check_feasibility("diving", "Bali")

        assert status == "feasible", f"Expected 'feasible', got '{status}'"

    def test_miami_skiing_infeasible(self):
        """Miami should return INFEASIBLE for skiing."""
        from app.planner.nodes_v2.vertical_specialist import check_feasibility

        status, reason, alternative = check_feasibility("skiing", "Miami")

        assert status == "infeasible", f"Expected 'infeasible', got '{status}'"

    def test_unknown_destination_feasible(self):
        """Unknown destinations should default to FEASIBLE."""
        from app.planner.nodes_v2.vertical_specialist import check_feasibility

        status, reason, alternative = check_feasibility("diving", "Some Random Place")

        assert status == "feasible", f"Expected 'feasible', got '{status}'"


class TestDubaiDiving:
    """Test Dubai diving knowledge (YC Demo: Deep Dive Dubai)."""

    def test_dubai_diving_content_exists(self):
        """Should have Dubai in diving knowledge base."""
        from app.planner.nodes_v2.vertical_specialist import DIVING_KNOWLEDGE

        destinations = DIVING_KNOWLEDGE.get("top_destinations", {})
        assert "dubai" in destinations, "Dubai should be in diving destinations"

    def test_deep_dive_dubai_in_content(self):
        """Should include Deep Dive Dubai recommendation."""
        from app.planner.nodes_v2.vertical_specialist import VerticalSpecialist

        specialist = VerticalSpecialist("diving")
        blocks = specialist.get_content_for_destination("Dubai")

        assert len(blocks) > 0, "Should have content blocks for Dubai"

        titles = [b.title for b in blocks]
        assert any(
            "Deep Dive Dubai" in t for t in titles
        ), f"Should include Deep Dive Dubai: {titles}"

    def test_dubai_content_has_logic_hook(self):
        """Dubai diving content should include logic_hook for UI."""
        from app.planner.nodes_v2.vertical_specialist import VerticalSpecialist

        specialist = VerticalSpecialist("diving")
        blocks = specialist.get_content_for_destination("Dubai")

        # Find Deep Dive Dubai block
        deep_dive_block = next((b for b in blocks if "Deep Dive Dubai" in b.title), None)
        assert deep_dive_block is not None, "Should have Deep Dive Dubai block"
        assert deep_dive_block.logic_hook is not None, "Should have logic_hook"
        assert "Indoor" in deep_dive_block.logic_hook or "Summer safe" in deep_dive_block.logic_hook

    def test_specialist_output_includes_feasibility(self):
        """Specialist output should include feasibility status for Dubai."""
        from app.planner.nodes_v2.vertical_specialist import VerticalSpecialist

        specialist = VerticalSpecialist("diving")
        state = GraphStateV2()
        state.trip_plan.destination = "Dubai"

        output = specialist.generate_output(state)

        assert (
            output.feasibility_status == "caveat"
        ), f"Expected 'caveat', got '{output.feasibility_status}'"
        assert output.feasibility_reason is not None


class TestLogicHooks:
    """Test logic_hook field propagation (YC Demo: Expert Recommendations)."""

    def test_bali_diving_has_logic_hooks(self):
        """Bali diving content should have logic_hooks."""
        from app.planner.nodes_v2.vertical_specialist import VerticalSpecialist

        specialist = VerticalSpecialist("diving")
        blocks = specialist.get_content_for_destination("Bali")

        # At least some blocks should have logic_hooks
        hooks = [b.logic_hook for b in blocks if b.logic_hook]
        assert (
            len(hooks) > 0
        ), f"Should have logic_hooks in Bali content: {[b.title for b in blocks]}"

    def test_egypt_diving_has_logic_hooks(self):
        """Egypt diving content should have logic_hooks."""
        from app.planner.nodes_v2.vertical_specialist import VerticalSpecialist

        specialist = VerticalSpecialist("diving")
        blocks = specialist.get_content_for_destination("Egypt")

        hooks = [b.logic_hook for b in blocks if b.logic_hook]
        assert len(hooks) > 0, "Egypt diving should have logic_hooks"

    def test_itinerary_block_schema_has_logic_hook(self):
        """ItineraryBlock schema should include logic_hook field."""
        from app.planner.state.schemas_v2 import ItineraryBlock

        block = ItineraryBlock(
            day=1,
            title="Test Activity",
            description="Test description",
            type="activity",
            logic_hook="Test tip - best visited early morning",
        )

        assert block.logic_hook == "Test tip - best visited early morning"


class TestConstraintFormatting:
    """Test constraint display formatting."""

    def test_diving_constraint_rule_format(self):
        """Diving constraints should use snake_case rules that map to readable titles."""
        from app.planner.nodes_v2.vertical_specialist import VerticalSpecialist

        specialist = VerticalSpecialist("diving")
        constraints = specialist.get_constraints()

        rules = [c.rule for c in constraints]
        assert "min_24h_buffer_after_dive" in rules, "Should have no-fly constraint"

        # This rule should map to "No-Fly Window (24h)" in frontend
        # The mapping is in frontend/components/plan/stages/S2StrategyView.tsx

    def test_caveat_constraint_injected(self):
        """Caveat status should inject a feasibility_caveat constraint."""
        from app.planner.nodes_v2.vertical_specialist import VerticalSpecialist

        specialist = VerticalSpecialist("diving")
        state = GraphStateV2()
        state.trip_plan.destination = "Dubai"  # Caveat destination

        output = specialist.generate_output(state)

        rules = [c.rule for c in output.constraints]
        assert (
            "feasibility_caveat" in rules
        ), f"Caveat should inject feasibility_caveat constraint: {rules}"


class TestLocalExpert:
    """Test Local Expert static knowledge and fallback behavior."""

    def test_dubai_local_expert_knowledge(self):
        """Dubai should have static local expert knowledge."""
        from app.planner.nodes_v2.local_expert import _get_static_local_knowledge

        knowledge = _get_static_local_knowledge("Dubai")

        assert len(knowledge.constraints) > 0, "Dubai should have constraints"
        assert len(knowledge.recommendations) > 0, "Dubai should have recommendations"

        # Check for specific Dubai content
        rec_titles = [r.title for r in knowledge.recommendations]
        assert any("Metro" in t for t in rec_titles), f"Should include Dubai Metro: {rec_titles}"

    def test_paris_local_expert_knowledge(self):
        """Paris should have static local expert knowledge."""
        from app.planner.nodes_v2.local_expert import _get_static_local_knowledge

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
        from app.planner.nodes_v2.local_expert import _get_static_local_knowledge

        knowledge = _get_static_local_knowledge("Random Unknown Place XYZ")

        assert len(knowledge.constraints) == 0, "Unknown place should have no constraints"
        assert len(knowledge.recommendations) == 0, "Unknown place should have no recommendations"

    def test_local_expert_logic_hooks(self):
        """Local Expert recommendations should have logic_hooks."""
        from app.planner.nodes_v2.local_expert import _get_static_local_knowledge

        knowledge = _get_static_local_knowledge("Tokyo")

        # All recommendations should have logic_hooks
        for rec in knowledge.recommendations:
            assert rec.logic_hook, f"Recommendation '{rec.title}' missing logic_hook"


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
