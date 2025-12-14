"""Performance benchmark tests for plan_graph functions.

Run with: pytest tests/langgraph/test_performance_benchmarks.py -v --benchmark-only

Requires: pip install pytest-benchmark
"""

# ruff: noqa: E402

import importlib.util
import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import pytest

# Check if pytest-benchmark is available
BENCHMARK_AVAILABLE = importlib.util.find_spec("pytest_benchmark") is not None

from app.plan_graph import (
    GraphState,
    TripInputs,
    _calculate_extraction_confidence,
    _compute_cache_key,
    _detect_short_circuit,
    _get_core_fields_state,
    extractor,
    jloads_safe,
    load_prompt,
    route_after_normalize,
)

# Skip all tests if pytest-benchmark not installed
pytestmark = pytest.mark.skipif(not BENCHMARK_AVAILABLE, reason="pytest-benchmark not installed")


class TestExtractorPerformance:
    """Benchmark tests for extractor function."""

    def test_extractor_simple_input(self, benchmark):
        """Extractor should process simple input quickly (<50ms)."""
        state = GraphState(
            user_text="I want to go to Paris",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        result = benchmark(extractor, state)
        assert result is not None

    def test_extractor_complex_input(self, benchmark):
        """Extractor should handle complex input reasonably."""
        state = GraphState(
            user_text="I want to fly business class from London to Tokyo next week, "
            "family of 4 with a budget of $10000, looking for 5-star hotels with pool",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        result = benchmark(extractor, state)
        assert result is not None

    def test_extractor_multi_destination(self, benchmark):
        """Extractor with multiple destinations."""
        state = GraphState(
            user_text="Trip from Rome to Paris, London, and Barcelona",
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        result = benchmark(extractor, state)
        assert result is not None


class TestShortCircuitPerformance:
    """Benchmark tests for short-circuit detection (<5ms target)."""

    def test_short_circuit_greeting(self, benchmark):
        """Greeting detection should be very fast."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = benchmark(_detect_short_circuit, "hi", state)
        assert result is not None
        assert result["type"] == "greeting"

    def test_short_circuit_acknowledgment(self, benchmark):
        """Acknowledgment detection should be very fast."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = benchmark(_detect_short_circuit, "thanks", state)
        assert result is not None

    def test_short_circuit_confirmation(self, benchmark):
        """Confirmation with pending action should be fast."""
        state = GraphState(
            user_text="",
            trip_inputs=TripInputs(),
            metadata={"pending_action": "generate_plan"},
        )
        result = benchmark(_detect_short_circuit, "yes", state)
        assert result is not None

    def test_short_circuit_no_match(self, benchmark):
        """Non-matching input should also be fast."""
        state = GraphState(user_text="", trip_inputs=TripInputs(), metadata={})
        result = benchmark(_detect_short_circuit, "I want to plan a trip", state)
        assert result is None  # Should not short-circuit


class TestRoutingPerformance:
    """Benchmark tests for routing functions (<1ms target)."""

    def test_route_after_normalize_simple(self, benchmark):
        """Routing decision should be very fast."""
        state = GraphState(
            user_text="test",
            trip_inputs=TripInputs(),
            flags={},
            metadata={},
        )
        result = benchmark(route_after_normalize, state)
        assert result == "router"

    def test_route_after_normalize_with_short_circuit(self, benchmark):
        """Short-circuit routing should be fast."""
        state = GraphState(
            user_text="hi",
            trip_inputs=TripInputs(),
            flags={"short_circuit": "greeting"},
            metadata={},
        )
        result = benchmark(route_after_normalize, state)
        assert result == "short_circuit_responder"

    def test_route_after_normalize_high_confidence(self, benchmark):
        """High confidence bypass check should be fast."""
        state = GraphState(
            user_text="ok",
            trip_inputs=TripInputs(
                destinations=["Paris"],
                origin="London",
                start_date="2025-06-01",
            ),
            flags={},
            metadata={
                "extraction_confidence": {
                    "overall": 0.95,
                    "level": "high",
                    "typo_suggestions": {},
                }
            },
        )
        result = benchmark(route_after_normalize, state)
        assert result in ("required_fields_node", "router")


class TestConfidenceCalculationPerformance:
    """Benchmark tests for confidence calculation (<10ms target)."""

    def test_confidence_simple(self, benchmark):
        """Simple confidence calculation should be fast."""
        parsed = {"destinations_delta": ["Paris"], "origin_delta": "London"}
        result = benchmark(
            _calculate_extraction_confidence,
            parsed,
            "from London to Paris",
            "regex",
            True,
        )
        assert result is not None
        assert hasattr(result, "overall")

    def test_confidence_complex(self, benchmark):
        """Complex confidence with multiple entities should be reasonable."""
        parsed = {
            "destinations_delta": ["Paris", "London", "Barcelona"],
            "origin_delta": "New York",
        }
        result = benchmark(
            _calculate_extraction_confidence,
            parsed,
            "from New York to Paris, London, and Barcelona",
            "regex",
            True,
        )
        assert result is not None


class TestCachePerformance:
    """Benchmark tests for caching operations (<1ms target)."""

    def test_cache_key_computation(self, benchmark):
        """Cache key computation should be very fast."""
        result = benchmark(
            _compute_cache_key,
            "required_fields",
            '{"destinations": ["Paris"]}',
            "quick_booking",
            "",
        )
        assert len(result) == 32

    def test_core_fields_state_serialization(self, benchmark):
        """Core fields state serialization should be fast."""
        trip = TripInputs(
            destinations=["Paris", "London"],
            origin="New York",
            start_date="2025-06-01",
            end_date="2025-06-15",
        )
        result = benchmark(_get_core_fields_state, trip)
        assert isinstance(result, str)


class TestPromptLoadingPerformance:
    """Benchmark tests for prompt loading."""

    def test_load_prompt_cached(self, benchmark):
        """Cached prompt loading should be very fast (<1ms)."""
        # First call to warm cache
        load_prompt("router")
        # Benchmark cached access
        result = benchmark(load_prompt, "router")
        assert isinstance(result, str)
        assert len(result) > 0


class TestJsonParsingPerformance:
    """Benchmark tests for JSON parsing."""

    def test_jloads_safe_valid_json(self, benchmark):
        """Valid JSON parsing should be fast."""
        json_str = '{"assistant_message": "Hello!", "parsed_updates": {"destinations": ["Paris"]}}'
        result = benchmark(jloads_safe, json_str)
        assert result.get("assistant_message") == "Hello!"

    def test_jloads_safe_malformed_json(self, benchmark):
        """Malformed JSON handling should still be reasonable."""
        json_str = '{"assistant_message": "Hello!", "incomplete'
        result = benchmark(jloads_safe, json_str)
        assert isinstance(result, dict)


class TestEndToEndPerformance:
    """End-to-end performance tests (with mocked LLM)."""

    def test_extractor_to_routing_flow(self, benchmark):
        """Full extractor + routing flow should be fast."""

        def flow():
            state = GraphState(
                user_text="I want to go to Paris from London next week",
                trip_inputs=TripInputs(),
                parsed_inputs={},
                chat_history=[],
                metadata={},
                thread_id="test",
                flags={},
            )
            state = extractor(state)
            route = route_after_normalize(state)
            return state, route

        result = benchmark(flow)
        state, route = result
        assert state is not None
        assert route in ("router", "short_circuit_responder", "required_fields_node")
