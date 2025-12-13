"""Test confidence scoring for entity extraction."""

import os
import sys

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

sys.path.insert(0, "c:\\Users\\Filippo\\Desktop\\nomadic\\backend")

from app.plan_graph import GraphState, TripInputs, extractor


def test_confidence_levels():
    """Test that confidence levels are correctly assigned."""
    tests = [
        ("I want to go to Patagonia", "high", "known place with grammar"),
        ("I want to go to Patogonia", "medium", "typo should lower confidence"),
        ("from London to Paris", "high", "grammar pattern with known places"),
        ("visit Georgia", "high", "known but ambiguous"),
        (
            "fly to Nice, France",
            "medium",
            "Nice is ambiguous, France clarifies but still has penalty",
        ),
        ("from New York to Tokyo", "high", "two known places with from/to"),
    ]

    failures = []
    for text, expected_level, description in tests:
        state = GraphState(
            user_text=text,
            trip_inputs=TripInputs(),
            parsed_inputs={},
            chat_history=[],
            metadata={},
            thread_id="test",
        )
        state = extractor(state)

        conf = state.metadata.get("extraction_confidence", {})
        actual_level = conf.get("level", "unknown")
        actual_overall = conf.get("overall", 0)

        if actual_level != expected_level:
            failures.append(
                f"FAIL: {description}\n  Input: {text!r}\n  "
                f"Expected: {expected_level}, Got: {actual_level} ({actual_overall:.2f})"
            )
        else:
            print(f"PASS: {description}")

    if failures:
        print("\n" + "=" * 60)
        for f in failures:
            print(f)
        print("=" * 60)
        raise AssertionError(f"{len(failures)} confidence level tests failed")
