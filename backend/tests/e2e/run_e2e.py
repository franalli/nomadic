#!/usr/bin/env python
"""
E2E Test Runner

A convenient script for running E2E conversation tests with various configurations.

Usage:
    # Run PR gate tests (fast)
    python -m tests.e2e.run_e2e --pr-gate

    # Run golden replay tests
    python -m tests.e2e.run_e2e --golden

    # Run generated scenario tests (comprehensive)
    python -m tests.e2e.run_e2e --generated

    # Run all tests
    python -m tests.e2e.run_e2e --all

    # Run single scenario interactively
    python -m tests.e2e.run_e2e --scenario simple_paris_trip

    # Generate and evaluate N scenarios
    python -m tests.e2e.run_e2e --generate 5
"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _e2e_tracing_enabled() -> bool:
    """Check if E2E LangSmith tracing is enabled."""
    return os.getenv("LANGSMITH_E2E_TRACING", "false").lower() == "true" and bool(
        os.getenv("LANGSMITH_API_KEY")
    )


def check_api_key():
    """Check that required API keys are set."""
    if not os.getenv("OPENAI_API_KEY"):
        print("❌ OPENAI_API_KEY not set. Please set it in your environment or .env file.")
        sys.exit(1)

    if _e2e_tracing_enabled():
        print("✅ LangSmith E2E tracing enabled")
    else:
        print(
            "⚠️  LangSmith E2E tracing disabled "
            "(set LANGSMITH_E2E_TRACING=true and LANGSMITH_API_KEY)"
        )


async def run_pr_gate():
    """Run PR gate tests."""
    import pytest

    print("\n" + "=" * 60)
    print("Running PR Gate E2E Tests")
    print("=" * 60 + "\n")

    result = pytest.main(
        [
            "tests/e2e/test_e2e_pr_gate.py",
            "-v",
            "--tb=short",
            "-x",  # Stop on first failure
            "--export-diagnostics",
        ]
    )

    return result == 0


async def run_golden():
    """Run golden replay tests."""
    import pytest

    print("\n" + "=" * 60)
    print("Running Golden Replay E2E Tests")
    print("=" * 60 + "\n")

    result = pytest.main(
        [
            "tests/e2e/test_e2e_golden_replays.py",
            "-v",
            "--tb=short",
            "--export-diagnostics",
        ]
    )

    return result == 0


async def run_generated():
    """Run generated scenario tests."""
    import pytest

    print("\n" + "=" * 60)
    print("Running Generated Scenario E2E Tests (this may take a while)")
    print("=" * 60 + "\n")

    result = pytest.main(
        [
            "tests/e2e/test_e2e_generated.py",
            "-v",
            "--tb=short",
            "--export-diagnostics",
        ]
    )

    return result == 0


async def run_single_scenario(scenario_name: str):
    """Run a single scenario interactively."""
    from tests.e2e.conversation_executor import ConversationExecutor
    from tests.e2e.evaluators import (
        ConstraintEvaluator,
        QualityEvaluator,
        SafetyEvaluator,
    )
    from tests.e2e.evaluators.base_evaluator import CompositeEvaluator
    from tests.e2e.scenario_generator import get_golden_scenarios

    print(f"\n🔍 Looking for scenario: {scenario_name}")

    # Find scenario
    scenarios = get_golden_scenarios()
    scenario = None
    for s in scenarios:
        if scenario_name in s.scenario_id:
            scenario = s
            break

    if not scenario:
        print(f"❌ Scenario '{scenario_name}' not found")
        print("Available scenarios:")
        for s in scenarios:
            print(f"  - {s.scenario_id}")
        return False

    print(f"✅ Found scenario: {scenario.scenario_id}")
    print(f"   Goal: {scenario.goal}")
    print(f"   Turns: {len(scenario.turns)}")

    # Execute
    print("\n🚀 Executing scenario...")
    executor = ConversationExecutor(enable_langsmith=_e2e_tracing_enabled())
    result = await executor.execute_scenario(scenario)

    # Display results
    print("\n📜 Conversation Transcript:")
    print("-" * 40)
    for turn in result.turns:
        print(f"\n👤 User: {turn.user_message}")
        print(f"🤖 Assistant: {turn.assistant_message[:200]}...")

    print("\n📊 Extracted Trip Inputs:")
    print(json.dumps(result.final_trip_inputs, indent=2))

    # Evaluate
    print("\n🎯 Running evaluation...")
    evaluators = CompositeEvaluator(
        [
            QualityEvaluator(),
            ConstraintEvaluator(),
            SafetyEvaluator(),
        ]
    )

    reports = await evaluators.evaluate(
        result=result,
        scenario_goal=scenario.goal,
        scenario_constraints=scenario.constraints.to_dict(),
    )

    print("\n📈 Evaluation Results:")
    print("-" * 40)
    for name, report in reports.items():
        status = "✅ PASS" if report.overall_passed else "❌ FAIL"
        print(f"{name}: {status} (score: {report.overall_score:.2f})")
        for r in report.results:
            indicator = "✓" if r.passed else "✗"
            print(f"  {indicator} {r.criterion}: {r.score:.2f}")

    avg_score = evaluators.get_aggregate_score(reports)
    print(f"\n🏆 Overall Score: {avg_score:.2f}")

    return True


async def generate_and_evaluate(count: int):
    """Generate and evaluate N scenarios."""
    from tests.e2e.conversation_executor import ConversationExecutor
    from tests.e2e.dataset_logger import LocalDatasetLogger
    from tests.e2e.evaluators import (
        ConstraintEvaluator,
        GroundednessEvaluator,
        QualityEvaluator,
        SafetyEvaluator,
        TravelLogicEvaluator,
    )
    from tests.e2e.evaluators.base_evaluator import CompositeEvaluator
    from tests.e2e.scenario_generator import ScenarioGenerator
    from tests.e2e.trace_summarizer import TraceSummarizer

    print(f"\n🎲 Generating {count} random scenarios...")

    generator = ScenarioGenerator(temperature=0.9)
    scenarios = await generator.generate_scenario_batch(count=count)

    print(f"✅ Generated {len(scenarios)} scenarios")

    executor = ConversationExecutor(enable_langsmith=_e2e_tracing_enabled())
    evaluators = CompositeEvaluator(
        [
            QualityEvaluator(),
            ConstraintEvaluator(),
            GroundednessEvaluator(),
            SafetyEvaluator(),
            TravelLogicEvaluator(),
        ]
    )

    summarizer = TraceSummarizer()
    logger = LocalDatasetLogger(output_dir="tests/e2e/generated_results")

    results_summary = []

    for i, scenario in enumerate(scenarios):
        print(f"\n{'='*60}")
        print(f"Scenario {i+1}/{len(scenarios)}: {scenario.scenario_id}")
        print(f"Goal: {scenario.goal}")
        print(f"Difficulty: {scenario.difficulty.level}")
        print("=" * 60)

        # Execute
        result = await executor.execute_scenario(scenario)

        if not result.success:
            print(f"❌ Execution failed: {result.errors_encountered}")
            results_summary.append(
                {
                    "scenario_id": scenario.scenario_id,
                    "success": False,
                    "error": str(result.errors_encountered),
                }
            )
            continue

        # Evaluate
        reports = await evaluators.evaluate(
            result=result,
            scenario_goal=scenario.goal,
            scenario_constraints=scenario.constraints.to_dict(),
        )

        avg_score = evaluators.get_aggregate_score(reports)
        all_passed = all(r.overall_passed for r in reports.values())

        # Log
        summary = summarizer.summarize_local(result)
        filepath = logger.log_evaluation(
            result=result,
            summary=summary,
            evaluation_reports=reports,
            scenario_goal=scenario.goal,
            scenario_constraints=scenario.constraints.to_dict(),
        )

        status = "✅ PASS" if all_passed else "❌ FAIL"
        print(f"{status} Score: {avg_score:.2f}")
        print(f"📁 Logged to: {filepath}")

        results_summary.append(
            {
                "scenario_id": scenario.scenario_id,
                "success": True,
                "passed": all_passed,
                "score": avg_score,
                "difficulty": scenario.difficulty.level,
            }
        )

    # Summary
    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)

    successful = [r for r in results_summary if r.get("success")]
    passed = [r for r in successful if r.get("passed")]

    print(f"Total scenarios: {len(results_summary)}")
    print(f"Executed successfully: {len(successful)}")
    print(f"Passed evaluation: {len(passed)}")

    if successful:
        avg = sum(r["score"] for r in successful) / len(successful)
        print(f"Average score: {avg:.2f}")

    return len(passed) == len(successful)


async def main():
    parser = argparse.ArgumentParser(description="E2E Test Runner")
    parser.add_argument("--pr-gate", action="store_true", help="Run PR gate tests")
    parser.add_argument("--golden", action="store_true", help="Run golden replay tests")
    parser.add_argument("--generated", action="store_true", help="Run generated scenario tests")
    parser.add_argument("--all", action="store_true", help="Run all tests")
    parser.add_argument("--scenario", type=str, help="Run a specific scenario by name")
    parser.add_argument("--generate", type=int, help="Generate and evaluate N scenarios")
    parser.add_argument(
        "--export-diagnostics",
        action="store_true",
        help="Export diagnostic reports (enabled by default for all test modes)",
    )
    parser.add_argument(
        "--diagnostics-dir",
        type=str,
        default="e2e_results",
        help="Directory for diagnostic output files",
    )

    args = parser.parse_args()

    check_api_key()

    success = True

    if args.scenario:
        success = await run_single_scenario(args.scenario)
    elif args.generate:
        success = await generate_and_evaluate(args.generate)
    elif args.all:
        success = await run_pr_gate() and await run_golden()
        if success:
            success = await run_generated()
    elif args.generated:
        success = await run_generated()
    elif args.golden:
        success = await run_golden()
    elif args.pr_gate:
        success = await run_pr_gate()
    else:
        # Default: run PR gate
        print("No test type specified. Running PR gate tests.")
        success = await run_pr_gate()

    sys.exit(0 if success else 1)

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
