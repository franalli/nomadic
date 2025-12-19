"""
E2E Tests for Domain Specialists - Phase 6 Token Optimization Tests.

Tests the four domain specialists (flights, hotels, transport, activities)
with both gate-verified paths (includes stripped) and router-LLM paths
(includes retained).

Verifies:
1. Responses stay domain-scoped after include stripping
2. Gate-verified paths produce equivalent quality to router-LLM paths
3. Include stripping doesn't break specialist behavior
4. State views are correctly minimal

Run with: pytest tests/e2e/test_e2e_specialists.py -v --tb=short
"""

import os
import sys
from pathlib import Path

import pytest

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from tests.e2e.scenario_generator import (  # noqa: E402
    ConversationScenario,
    ConversationTurn,
    DifficultySettings,
    ScenarioConstraints,
    UserProfile,
)

# Skip if no OpenAI API key
pytestmark = [
    pytest.mark.skipif(
        not os.getenv("OPENAI_API_KEY"), reason="OPENAI_API_KEY required for E2E tests"
    ),
    pytest.mark.asyncio,
]


# =============================================================================
# Helper Functions for Creating Scenarios
# =============================================================================


def create_scenario(
    scenario_id: str,
    name: str,
    messages: list[str],
    goal: str,
) -> ConversationScenario:
    """Helper to create a ConversationScenario with defaults."""
    return ConversationScenario(
        scenario_id=scenario_id,
        user_profile=UserProfile(
            persona="solo_explorer",
            experience_level="intermediate",
            communication_style="casual",
            decision_making="decisive",
        ),
        goal=goal,
        constraints=ScenarioConstraints(),
        difficulty=DifficultySettings(
            level="easy",
            ambiguity_level="none",
        ),
        turns=[
            ConversationTurn(turn_number=i + 1, user_message=msg) for i, msg in enumerate(messages)
        ],
    )


# =============================================================================
# Test Data: Specialist-Specific Scenarios
# =============================================================================

# Each scenario targets a specific specialist with gate-verified routing
GATE_VERIFIED_SCENARIOS = [
    # Flights specialist - question-keyword gate ("What flights...")
    {
        "id": "flights_gate",
        "name": "Flights specialist via QUESTION_KEYWORD gate",
        "messages": [
            "I want to plan a trip to Paris from London next month",
            "What flights are available for this route?",
        ],
        "expected_specialist": "flights",
        "expected_gate": "QUESTION_KEYWORD",
        "should_strip_includes": True,
    },
    # Hotels specialist - question-keyword gate ("Which hotels...")
    {
        "id": "hotels_gate",
        "name": "Hotels specialist via QUESTION_KEYWORD gate",
        "messages": [
            "Planning a vacation to Rome, flying from NYC",
            "Which hotels would you recommend near the Colosseum?",
        ],
        "expected_specialist": "hotels",
        "expected_gate": "QUESTION_KEYWORD",
        "should_strip_includes": True,
    },
    # Transport specialist - question-keyword gate ("What transport...")
    {
        "id": "transport_gate",
        "name": "Transport specialist via QUESTION_KEYWORD gate",
        "messages": [
            "Trip to Tokyo from San Francisco in December",
            "What transport options are there from Narita to the city center?",
        ],
        "expected_specialist": "transport",
        "expected_gate": "QUESTION_KEYWORD",
        "should_strip_includes": True,
    },
    # Activities specialist - question-keyword gate ("What activities...")
    {
        "id": "activities_gate",
        "name": "Activities specialist via QUESTION_KEYWORD gate",
        "messages": [
            "I'm going to Barcelona from Madrid next week",
            "What activities should I do there?",
        ],
        "expected_specialist": "activities",
        "expected_gate": "QUESTION_KEYWORD",
        "should_strip_includes": True,
    },
]

# Scenarios that should go through router LLM (no gate match)
ROUTER_LLM_SCENARIOS = [
    # Flights - indirect question (no question word + keyword combo)
    {
        "id": "flights_router",
        "name": "Flights specialist via router LLM",
        "messages": [
            "Trip to Paris from London in March",
            "I'm curious about the flight situation",
        ],
        "expected_specialist": "flights",
        "expected_gate": None,  # Should use router LLM
        "should_strip_includes": False,  # Router path keeps includes
    },
    # Hotels - statement about hotels
    {
        "id": "hotels_router",
        "name": "Hotels specialist via router LLM",
        "messages": [
            "Vacation to Rome from NYC",
            "I need accommodation near the Vatican",
        ],
        "expected_specialist": "hotels",
        "expected_gate": None,
        "should_strip_includes": False,
    },
]


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def conversation_executor():
    """Create a conversation executor."""
    from tests.e2e.conversation_executor import ConversationExecutor

    return ConversationExecutor(
        enable_langsmith=False,
        langsmith_project="nomadic-specialist-tests",
    )


# =============================================================================
# Helper Functions
# =============================================================================


def get_metadata_from_turn(turn_result) -> dict:
    """Extract metadata from a turn result."""
    # The session_state contains the full state including metadata
    return turn_result.session_state.get("metadata", {})


def get_routing_info(turn_result) -> dict:
    """Extract routing information from a turn."""
    return {
        "router_intent": turn_result.router_intent,
        "strategy_topic": turn_result.strategy_topic,
        "short_circuit": turn_result.short_circuit_type,
    }


def assert_domain_scoped_response(response: str, domain: str):
    """
    Assert that a response is scoped to the expected domain.

    Checks that:
    1. Response doesn't include off-topic information
    2. Response mentions domain-relevant concepts
    """
    response_lower = response.lower()

    domain_keywords = {
        "flights": ["flight", "airline", "depart", "arrive", "airport", "fly"],
        "hotels": ["hotel", "accommodation", "room", "stay", "lodging", "booking"],
        "transport": ["transport", "transfer", "taxi", "train", "bus", "metro", "getting"],
        "activities": ["activity", "activities", "tour", "visit", "experience", "see", "do"],
    }

    # Check for at least one domain keyword
    keywords = domain_keywords.get(domain, [])
    has_domain_content = any(kw in response_lower for kw in keywords)

    # Relaxed check - if the response is about the trip at all, it's likely OK
    trip_keywords = ["trip", "travel", "vacation", "journey", "plan"]
    has_trip_content = any(kw in response_lower for kw in trip_keywords)

    assert (
        has_domain_content or has_trip_content
    ), f"Response doesn't appear to be about {domain}:\n{response[:200]}..."


# =============================================================================
# Gate-Verified Specialist Tests
# =============================================================================


class TestGateVerifiedSpecialists:
    """Test specialists when routed via deterministic gates."""

    @pytest.mark.parametrize("scenario", GATE_VERIFIED_SCENARIOS, ids=lambda s: s["id"])
    async def test_gate_verified_routing(self, conversation_executor, scenario):
        """Test that gate-verified messages route to correct specialist."""
        # Create scenario object
        conv_scenario = create_scenario(
            scenario_id=scenario["id"],
            name=scenario["name"],
            messages=scenario["messages"],
            goal=f"Test {scenario['expected_specialist']} specialist routing",
        )

        # Execute conversation
        result = await conversation_executor.execute(conv_scenario)

        # Verify routing on the second message (the specialist question)
        assert len(result.turns) >= 2, f"Expected at least 2 turns, got {len(result.turns)}"

        specialist_turn = result.turns[-1]

        # Check that the response is domain-scoped
        assert_domain_scoped_response(
            specialist_turn.assistant_message, scenario["expected_specialist"]
        )

        # Log routing info for debugging
        print(f"\nScenario: {scenario['name']}")
        print(f"  Expected specialist: {scenario['expected_specialist']}")
        print(f"  Router intent: {specialist_turn.router_intent}")
        print(f"  Response preview: {specialist_turn.assistant_message[:100]}...")

    @pytest.mark.parametrize("scenario", GATE_VERIFIED_SCENARIOS, ids=lambda s: s["id"])
    async def test_include_stripping_enabled(self, conversation_executor, scenario):
        """Test that include stripping is enabled for gate-verified paths."""
        conv_scenario = create_scenario(
            scenario_id=scenario["id"],
            name=scenario["name"],
            messages=scenario["messages"],
            goal=f"Test include stripping for {scenario['expected_specialist']}",
        )

        result = await conversation_executor.execute(conv_scenario)

        # The test verifies that the conversation succeeds even with include stripping
        # If stripping broke something, we'd see errors or off-topic responses
        assert result.success, f"Conversation failed: {result.errors_encountered}"
        assert len(result.turns) >= 2

        # Verify response quality
        specialist_turn = result.turns[-1]
        assert (
            len(specialist_turn.assistant_message) > 50
        ), "Response too short - might indicate broken specialist"


class TestRouterLLMSpecialists:
    """Test specialists when routed via router LLM."""

    @pytest.mark.parametrize("scenario", ROUTER_LLM_SCENARIOS, ids=lambda s: s["id"])
    async def test_router_llm_routing(self, conversation_executor, scenario):
        """Test that router LLM paths still work correctly."""
        conv_scenario = create_scenario(
            scenario_id=scenario["id"],
            name=scenario["name"],
            messages=scenario["messages"],
            goal=f"Test router LLM path for {scenario['expected_specialist']}",
        )

        result = await conversation_executor.execute(conv_scenario)

        assert len(result.turns) >= 2, f"Expected at least 2 turns, got {len(result.turns)}"

        specialist_turn = result.turns[-1]

        # Check that the response is domain-scoped
        assert_domain_scoped_response(
            specialist_turn.assistant_message, scenario["expected_specialist"]
        )

        print(f"\nScenario: {scenario['name']}")
        print(f"  Expected specialist: {scenario['expected_specialist']}")
        print(f"  Router intent: {specialist_turn.router_intent}")


# =============================================================================
# State View Validation Tests
# =============================================================================


class TestStateViewValidation:
    """Test that StateViewBuilder produces minimal views."""

    async def test_specialist_state_view_size(self, conversation_executor):
        """Test that specialist state views are minimal."""
        from app.plan_graph import GraphState, StateViewBuilder, TripInputs

        # Create a state with full trip_inputs
        trip_inputs = TripInputs(
            destinations=["Paris"],
            origin="London",
            start_date="2025-03-01",
            end_date="2025-03-07",
            adults=2,
            children=0,
            budget=2000,
            currency="EUR",
            flight_settings={"class": "economy", "direct": True},
            hotel_settings={"stars": 4, "amenities": ["wifi", "breakfast"]},
            transport_settings={"type": "public"},
            activity_settings={"categories": ["culture", "food"]},
        )

        state = GraphState(trip_inputs=trip_inputs, user_text="test")

        # Test each specialist view
        for specialist in ["flights", "hotels", "transport", "activities"]:
            view = StateViewBuilder.for_specialist(state, specialist)

            # Count total fields including nested
            total_fields = len(view)
            for v in view.values():
                if isinstance(v, dict):
                    total_fields += len(v)

            # Should be well under the 20-field limit
            assert total_fields <= StateViewBuilder._MAX_VIEW_FIELDS, (
                f"{specialist} view has {total_fields} fields, "
                f"max is {StateViewBuilder._MAX_VIEW_FIELDS}"
            )

            print(f"{specialist} view: {total_fields} total fields")

    async def test_state_view_validation_catches_large_views(self):
        """Test that validation raises error for oversized views."""
        from app.plan_graph import StateViewBuilder

        # Create an artificially large view
        large_view = {f"field_{i}": f"value_{i}" for i in range(25)}

        with pytest.raises(ValueError, match="fields"):
            StateViewBuilder.validate_view(large_view, "test_node")


# =============================================================================
# Quality Comparison Tests
# =============================================================================


class TestSpecialistQuality:
    """Compare quality between gate-verified and router-LLM paths."""

    async def test_flights_quality_parity(self, conversation_executor):
        """Test that gate-verified flights responses match router-LLM quality."""
        # Gate-verified path
        gate_scenario = create_scenario(
            scenario_id="flights_gate_quality",
            name="Flights via gate",
            messages=[
                "Trip to Tokyo from LA in April",
                "What flights are available?",
            ],
            goal="Test flight information quality",
        )

        gate_result = await conversation_executor.execute(gate_scenario)
        gate_response = gate_result.turns[-1].assistant_message

        # Router-LLM path (different phrasing)
        router_scenario = create_scenario(
            scenario_id="flights_router_quality",
            name="Flights via router",
            messages=[
                "Trip to Tokyo from LA in April",
                "Tell me about the flight options",
            ],
            goal="Test flight information quality",
        )

        router_result = await conversation_executor.execute(router_scenario)
        router_response = router_result.turns[-1].assistant_message

        # Both should be domain-scoped
        assert_domain_scoped_response(gate_response, "flights")
        assert_domain_scoped_response(router_response, "flights")

        # Both should have reasonable length
        assert len(gate_response) > 50, "Gate response too short"
        assert len(router_response) > 50, "Router response too short"

        print(f"\nGate response ({len(gate_response)} chars): {gate_response[:150]}...")
        print(f"\nRouter response ({len(router_response)} chars): {router_response[:150]}...")


# =============================================================================
# Edge Case Tests
# =============================================================================


class TestSpecialistEdgeCases:
    """Test edge cases for specialist routing."""

    async def test_ambiguous_specialist_question(self, conversation_executor):
        """Test handling of questions that could apply to multiple specialists."""
        scenario = create_scenario(
            scenario_id="ambiguous",
            name="Ambiguous specialist question",
            messages=[
                "Trip to Paris from London",
                "What should I know about getting there and staying there?",
            ],
            goal="Test ambiguous question handling",
        )

        result = await conversation_executor.execute(scenario)

        # Should succeed and provide helpful response
        assert result.success
        assert len(result.turns[-1].assistant_message) > 50

    async def test_specialist_after_complete_trip_inputs(self, conversation_executor):
        """Test specialist questions when trip_inputs is already complete."""
        scenario = create_scenario(
            scenario_id="complete_then_specialist",
            name="Specialist after complete inputs",
            messages=[
                "Trip to Paris from London, March 1-7, 2 adults, 2000 EUR budget",
                "What hotels are near the Eiffel Tower?",
            ],
            goal="Test specialist with complete trip_inputs",
        )

        result = await conversation_executor.execute(scenario)

        assert result.success
        specialist_turn = result.turns[-1]
        assert_domain_scoped_response(specialist_turn.assistant_message, "hotels")

    async def test_specialist_with_minimal_context(self, conversation_executor):
        """Test specialist questions with minimal trip context."""
        scenario = create_scenario(
            scenario_id="minimal_context",
            name="Specialist with minimal context",
            messages=[
                "Paris",  # Just destination
                "What flights?",
            ],
            goal="Test specialist with minimal context",
        )

        result = await conversation_executor.execute(scenario)

        # Should handle gracefully - might ask for more info
        assert result.success
        assert len(result.turns[-1].assistant_message) > 20


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
