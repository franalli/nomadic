"""
Post-run diagnostic system for E2E tests.

Provides:
- Failure categorization and aggregation
- LangSmith trace URL generation
- Rich diagnostic exports (JSON, Markdown)
- Console summary with actionable information

The goal is that "right after we run all tests, we should have all the
information available to diagnose issues and get right to fixing them."
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class FailureCategory(str, Enum):
    """Categories for grouping test failures."""

    ROUTING_ERROR = "routing_error"
    CONSTRAINT_VIOLATION = "constraint_violation"
    GROUNDEDNESS_ISSUE = "groundedness_issue"
    STATE_REGRESSION = "state_regression"
    SAFETY_ISSUE = "safety_issue"
    QUALITY_ISSUE = "quality_issue"
    EXECUTION_ERROR = "execution_error"
    UNKNOWN = "unknown"


@dataclass
class ThresholdCheck:
    """Result of a threshold check against env-configured targets."""

    metric_name: str
    actual_value: float
    target_value: float
    passed: bool
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_name": self.metric_name,
            "actual_value": self.actual_value,
            "target_value": self.target_value,
            "passed": self.passed,
            "description": self.description,
        }


def check_thresholds_from_stats(graph_stats: Dict[str, Any]) -> List[ThresholdCheck]:
    """
    Check graph stats against env-configured thresholds.

    Uses ROUTER_CALL_RATE_TARGET and TEMPLATE_HIT_RATE_TARGET from environment.
    Returns a list of ThresholdCheck results.
    """
    checks: List[ThresholdCheck] = []

    # Get target thresholds from environment
    router_call_rate_target = float(os.getenv("ROUTER_CALL_RATE_TARGET", "0.30"))
    template_hit_rate_target = float(os.getenv("TEMPLATE_HIT_RATE_TARGET", "0.85"))

    # Extract routing stats
    routing_stats = graph_stats.get("routing", {})
    total_turns = routing_stats.get("total_turns", 0)

    if total_turns > 0:
        # Check router call rate (lower is better - we want short-circuits)
        router_calls = routing_stats.get("router_calls", 0)
        router_call_rate = router_calls / total_turns
        checks.append(
            ThresholdCheck(
                metric_name="router_call_rate",
                actual_value=round(router_call_rate, 3),
                target_value=router_call_rate_target,
                passed=router_call_rate <= router_call_rate_target,
                description=(
                    f"Router called {router_calls}/{total_turns} turns "
                    + f"({router_call_rate:.1%})"
                ),
            )
        )

    # Check template hit rate (higher is better)
    template_stats = graph_stats.get("template", {})
    template_attempts = template_stats.get("attempts", 0)
    template_hits = template_stats.get("hits", 0)

    if template_attempts > 0:
        template_hit_rate = template_hits / template_attempts
        checks.append(
            ThresholdCheck(
                metric_name="template_hit_rate",
                actual_value=round(template_hit_rate, 3),
                target_value=template_hit_rate_target,
                passed=template_hit_rate >= template_hit_rate_target,
                description=(
                    f"Template hit {template_hits}/{template_attempts} attempts "
                    + f"({template_hit_rate:.1%})"
                ),
            )
        )

    # Check cache hit rates (informational, no hard threshold)
    extractor_stats = graph_stats.get("extractor", {})
    extractor_total = extractor_stats.get("full_calls", 0) + extractor_stats.get("light_calls", 0)
    extractor_cache_hits = extractor_stats.get("cache_hits", 0)

    if extractor_total > 0:
        cache_rate = extractor_cache_hits / (extractor_total + extractor_cache_hits)
        checks.append(
            ThresholdCheck(
                metric_name="extractor_cache_rate",
                actual_value=round(cache_rate, 3),
                target_value=0.0,  # Informational only
                passed=True,  # Always passes (informational)
                description=(
                    f"Extractor cache hit {extractor_cache_hits}/"
                    + f"{extractor_total + extractor_cache_hits} ({cache_rate:.1%})"
                ),
            )
        )

    strategy_stats = graph_stats.get("strategy", {})
    strategy_cache_hits = strategy_stats.get("cache_hits", 0)
    strategy_calls = strategy_stats.get("calls", 0)

    if strategy_calls > 0 or strategy_cache_hits > 0:
        total_strategy = strategy_calls + strategy_cache_hits
        strategy_cache_rate = strategy_cache_hits / total_strategy if total_strategy > 0 else 0
        checks.append(
            ThresholdCheck(
                metric_name="strategy_cache_rate",
                actual_value=round(strategy_cache_rate, 3),
                target_value=0.0,  # Informational only
                passed=True,  # Always passes (informational)
                description=(
                    f"Strategy cache hit {strategy_cache_hits}/{total_strategy} "
                    + f"({strategy_cache_rate:.1%})"
                ),
            )
        )

    return checks


@dataclass
class DiagnosticFailure:
    """Detailed information about a single test failure."""

    # Test identification
    test_name: str
    scenario_id: str

    # Failure details
    evaluator: str
    criterion: str
    score: float
    feedback: str
    category: FailureCategory

    # Context for debugging
    turn_number: Optional[int] = None
    node_name: Optional[str] = None
    user_message: Optional[str] = None
    assistant_response: Optional[str] = None
    trip_inputs_at_failure: Optional[Dict[str, Any]] = None

    # LangSmith trace info
    langsmith_run_id: Optional[str] = None
    langsmith_url: Optional[str] = None

    # Error information (for execution errors)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "test_name": self.test_name,
            "scenario_id": self.scenario_id,
            "evaluator": self.evaluator,
            "criterion": self.criterion,
            "score": self.score,
            "feedback": self.feedback,
            "category": self.category.value,
            "turn_number": self.turn_number,
            "node_name": self.node_name,
            "user_message": self.user_message,
            "assistant_response": self.assistant_response,
            "trip_inputs_at_failure": self.trip_inputs_at_failure,
            "langsmith_run_id": self.langsmith_run_id,
            "langsmith_url": self.langsmith_url,
            "error_type": self.error_type,
            "error_message": self.error_message,
            "traceback": self.traceback,
        }


@dataclass
class TestOutcome:
    """Outcome of a single test."""

    test_name: str
    scenario_id: str
    passed: bool
    duration_seconds: float
    evaluator_scores: Dict[str, float] = field(default_factory=dict)
    failures: List[DiagnosticFailure] = field(default_factory=list)
    run_ids: List[str] = field(default_factory=list)

    # Token and timing metrics
    total_tokens: int = 0
    total_llm_calls: int = 0
    total_llm_time_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "test_name": self.test_name,
            "scenario_id": self.scenario_id,
            "passed": self.passed,
            "duration_seconds": self.duration_seconds,
            "evaluator_scores": self.evaluator_scores,
            "failures": [f.to_dict() for f in self.failures],
            "run_ids": self.run_ids,
            "total_tokens": self.total_tokens,
            "total_llm_calls": self.total_llm_calls,
            "total_llm_time_ms": self.total_llm_time_ms,
        }


class FailureCategorizer:
    """Categorizes failures based on evaluator and criterion."""

    CATEGORY_MAPPING = {
        # Evaluator-based mapping
        "safety_evaluator": FailureCategory.SAFETY_ISSUE,
        "constraint_evaluator": FailureCategory.CONSTRAINT_VIOLATION,
        "groundedness_evaluator": FailureCategory.GROUNDEDNESS_ISSUE,
        "quality_evaluator": FailureCategory.QUALITY_ISSUE,
        "routing_evaluator": FailureCategory.ROUTING_ERROR,
        "travel_logic_evaluator": FailureCategory.CONSTRAINT_VIOLATION,
        # Criterion-based mapping
        "routing_accuracy": FailureCategory.ROUTING_ERROR,
        "state_transition_validity": FailureCategory.STATE_REGRESSION,
        "constraint_adherence": FailureCategory.CONSTRAINT_VIOLATION,
        "groundedness": FailureCategory.GROUNDEDNESS_ISSUE,
        "safety_compliance": FailureCategory.SAFETY_ISSUE,
    }

    @classmethod
    def categorize(cls, evaluator: str, criterion: str) -> FailureCategory:
        """Determine the failure category based on evaluator and criterion."""
        # Check criterion first (more specific)
        criterion_lower = criterion.lower().replace(" ", "_")
        if criterion_lower in cls.CATEGORY_MAPPING:
            return cls.CATEGORY_MAPPING[criterion_lower]

        # Fall back to evaluator
        evaluator_lower = evaluator.lower().replace(" ", "_")
        if evaluator_lower in cls.CATEGORY_MAPPING:
            return cls.CATEGORY_MAPPING[evaluator_lower]

        return FailureCategory.UNKNOWN


def generate_langsmith_url(
    run_id: str,
    project: Optional[str] = None,
    endpoint: Optional[str] = None,
) -> str:
    """
    Generate a clickable LangSmith URL for a trace.

    Args:
        run_id: The LangSmith run ID
        project: The project name (defaults to env var or 'nomadic-e2e-tests')
        endpoint: The API endpoint (for determining region)

    Returns:
        Full URL to view the trace in LangSmith UI
    """
    # Determine the base URL based on endpoint
    if endpoint and "eu.api" in endpoint:
        base_url = "https://eu.smith.langchain.com"
    else:
        base_url = "https://smith.langchain.com"

    # Get project name
    if not project:
        project = os.getenv("LANGCHAIN_PROJECT", "nomadic-e2e-tests")

    return f"{base_url}/public/{project}/r/{run_id}"


@dataclass
class DiagnosticReport:
    """
    Complete diagnostic report for a test session.

    Aggregates all test outcomes and provides analysis for debugging.
    """

    # Session metadata
    session_id: str = ""
    timestamp: str = ""
    project_name: str = ""
    langsmith_endpoint: str = ""

    # Test outcomes
    outcomes: List[TestOutcome] = field(default_factory=list)

    # Aggregated failures by category
    failures_by_category: Dict[str, List[DiagnosticFailure]] = field(default_factory=dict)

    # Summary statistics
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    total_duration_seconds: float = 0.0

    # Aggregated token and timing metrics
    total_tokens: int = 0
    total_llm_calls: int = 0
    total_llm_time_ms: float = 0.0

    # Aggregated graph stats from all scenarios
    aggregated_graph_stats: Dict[str, Any] = field(default_factory=dict)

    # Threshold checks against env-configured targets
    threshold_checks: List[ThresholdCheck] = field(default_factory=list)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()
        if not self.session_id:
            self.session_id = datetime.now().strftime("%Y%m%d-%H%M%S")

    def add_outcome(self, outcome: TestOutcome) -> None:
        """Add a test outcome and update statistics."""
        self.outcomes.append(outcome)
        self.total_tests += 1
        self.total_duration_seconds += outcome.duration_seconds

        # Accumulate token and timing metrics
        self.total_tokens += outcome.total_tokens
        self.total_llm_calls += outcome.total_llm_calls
        self.total_llm_time_ms += outcome.total_llm_time_ms

        if outcome.passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1

            # Categorize failures
            for failure in outcome.failures:
                category = failure.category.value
                if category not in self.failures_by_category:
                    self.failures_by_category[category] = []
                self.failures_by_category[category].append(failure)

    def get_summary_stats(self) -> Dict[str, Any]:
        """Get summary statistics."""
        return {
            "total_tests": self.total_tests,
            "passed": self.passed_tests,
            "failed": self.failed_tests,
            "pass_rate": self.passed_tests / self.total_tests if self.total_tests else 0,
            "total_duration_seconds": round(self.total_duration_seconds, 2),
            "failures_by_category": {
                cat: len(failures) for cat, failures in self.failures_by_category.items()
            },
            # Token and timing metrics
            "total_tokens": self.total_tokens,
            "total_llm_calls": self.total_llm_calls,
            "total_llm_time_ms": round(self.total_llm_time_ms, 2),
            "avg_tokens_per_test": (
                round(self.total_tokens / self.total_tests, 1) if self.total_tests else 0
            ),
            "avg_llm_time_ms_per_test": (
                round(self.total_llm_time_ms / self.total_tests, 2) if self.total_tests else 0
            ),
        }

    def get_evaluator_breakdown(self) -> Dict[str, Dict[str, int]]:
        """Get pass/fail breakdown by evaluator."""
        evaluator_stats: Dict[str, Dict[str, int]] = {}

        for outcome in self.outcomes:
            for evaluator, score in outcome.evaluator_scores.items():
                if evaluator not in evaluator_stats:
                    evaluator_stats[evaluator] = {"passed": 0, "failed": 0}

                # Consider score >= 0.7 as passed
                if score >= 0.7:
                    evaluator_stats[evaluator]["passed"] += 1
                else:
                    evaluator_stats[evaluator]["failed"] += 1

        return evaluator_stats

    def get_top_failures(self, n: int = 5) -> List[DiagnosticFailure]:
        """Get the N most severe failures (lowest scores)."""
        all_failures = []
        for failures in self.failures_by_category.values():
            all_failures.extend(failures)

        # Sort by score (lowest first)
        all_failures.sort(key=lambda f: f.score)
        return all_failures[:n]

    def set_graph_stats(self, graph_stats: Dict[str, Any]) -> None:
        """Set aggregated graph stats and run threshold checks."""
        self.aggregated_graph_stats = graph_stats
        self.threshold_checks = check_thresholds_from_stats(graph_stats)

    def get_failed_threshold_checks(self) -> List[ThresholdCheck]:
        """Get threshold checks that failed."""
        return [c for c in self.threshold_checks if not c.passed]

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "project_name": self.project_name,
            "langsmith_endpoint": self.langsmith_endpoint,
            "summary": self.get_summary_stats(),
            "evaluator_breakdown": self.get_evaluator_breakdown(),
            "outcomes": [o.to_dict() for o in self.outcomes],
            "failures_by_category": {
                cat: [f.to_dict() for f in failures]
                for cat, failures in self.failures_by_category.items()
            },
            "aggregated_graph_stats": self.aggregated_graph_stats,
            "threshold_checks": [c.to_dict() for c in self.threshold_checks],
        }

    def to_json(self, indent: int = 2) -> str:
        """Export as JSON string."""
        return json.dumps(self.to_dict(), indent=indent)

    def to_markdown(self) -> str:
        """Export as markdown for easy reading."""
        lines = []

        # Header
        lines.append("# E2E Test Diagnostic Report")
        lines.append("")
        lines.append(f"**Session:** {self.session_id}")
        lines.append(f"**Timestamp:** {self.timestamp}")
        lines.append(f"**Project:** {self.project_name}")
        lines.append("")

        # Summary
        stats = self.get_summary_stats()
        lines.append("## Summary")
        lines.append("")
        lines.append(f"- **Total Tests:** {stats['total_tests']}")
        lines.append(f"- **Passed:** {stats['passed']}")
        lines.append(f"- **Failed:** {stats['failed']}")
        lines.append(f"- **Pass Rate:** {stats['pass_rate']:.1%}")
        lines.append(f"- **Duration:** {stats['total_duration_seconds']:.2f}s")
        lines.append("")

        # Evaluator breakdown
        evaluator_stats = self.get_evaluator_breakdown()
        if evaluator_stats:
            lines.append("## Evaluator Breakdown")
            lines.append("")
            lines.append("| Evaluator | Passed | Failed |")
            lines.append("|-----------|--------|--------|")
            for evaluator, counts in sorted(evaluator_stats.items()):
                lines.append(f"| {evaluator} | {counts['passed']} | {counts['failed']} |")
            lines.append("")

        # Failures by category
        if self.failures_by_category:
            lines.append("## Failures by Category")
            lines.append("")
            for category, failures in sorted(self.failures_by_category.items()):
                lines.append(f"### {category.replace('_', ' ').title()} ({len(failures)})")
                lines.append("")
                for failure in failures[:10]:  # Limit to 10 per category
                    lines.append(f"#### {failure.scenario_id}")
                    lines.append("")
                    lines.append(f"- **Test:** {failure.test_name}")
                    lines.append(f"- **Evaluator:** {failure.evaluator}")
                    lines.append(f"- **Criterion:** {failure.criterion}")
                    lines.append(f"- **Score:** {failure.score:.2f}")
                    lines.append(f"- **Feedback:** {failure.feedback}")
                    if failure.langsmith_url:
                        trace_link = f"[{failure.langsmith_run_id}]({failure.langsmith_url})"
                        lines.append(f"- **Trace:** {trace_link}")
                    if failure.turn_number:
                        lines.append(f"- **Turn:** {failure.turn_number}")
                    if failure.user_message:
                        lines.append(f"- **User Message:** {failure.user_message[:200]}...")
                    lines.append("")
                if len(failures) > 10:
                    lines.append(f"*...and {len(failures) - 10} more*")
                    lines.append("")

        return "\n".join(lines)

    def print_console_summary(self) -> None:
        """Print a compact summary to the console."""
        stats = self.get_summary_stats()

        print("\n" + "=" * 70)
        print("E2E DIAGNOSTIC SUMMARY")
        print("=" * 70)

        # Pass/fail overview
        status = "✅ ALL PASSED" if self.failed_tests == 0 else "❌ FAILURES DETECTED"
        print(f"\n{status}")
        print(f"Tests: {stats['passed']}/{stats['total_tests']} passed ({stats['pass_rate']:.1%})")
        print(f"Duration: {stats['total_duration_seconds']:.2f}s")

        # Token and timing metrics
        if stats.get("total_llm_calls", 0) > 0:
            print("\n🪙 LLM Metrics:")
            tokens_msg = (
                f"   Tokens: {stats['total_tokens']:,} total "
                f"({stats['avg_tokens_per_test']:,.0f} avg/test)"
            )
            print(tokens_msg)
            print(f"   LLM Calls: {stats['total_llm_calls']:,}")
            if stats.get("total_llm_time_ms", 0) > 0:
                time_msg = (
                    f"   LLM Time: {stats['total_llm_time_ms']:,.0f}ms "
                    f"({stats['avg_llm_time_ms_per_test']:,.0f}ms avg/test)"
                )
                print(time_msg)

        # Evaluator breakdown
        evaluator_stats = self.get_evaluator_breakdown()
        if evaluator_stats and self.failed_tests > 0:
            print("\n📊 Evaluator Breakdown:")
            for evaluator, counts in sorted(evaluator_stats.items()):
                status_icon = "✅" if counts["failed"] == 0 else "❌"
                passed_cnt, failed_cnt = counts["passed"], counts["failed"]
                print(f"   {status_icon} {evaluator}: {passed_cnt} passed, {failed_cnt} failed")

        # Category breakdown
        if self.failures_by_category:
            print("\n📋 Failures by Category:")
            for category, failures in sorted(self.failures_by_category.items()):
                print(f"   • {category.replace('_', ' ').title()}: {len(failures)}")

        # Threshold checks
        if self.threshold_checks:
            failed_checks = self.get_failed_threshold_checks()
            if failed_checks:
                print("\n⚠️  Threshold Checks FAILED:")
                for check in failed_checks:
                    print(
                        f"   ❌ {check.metric_name}: {check.actual_value:.1%} "
                        f"vs target {check.target_value:.1%}"
                    )
                    print(f"      {check.description}")
            else:
                print("\n✅ All Threshold Checks Passed:")
            # Show all checks
            for check in self.threshold_checks:
                icon = "✅" if check.passed else "❌"
                if check.target_value > 0:  # Skip informational checks
                    print(
                        f"   {icon} {check.metric_name}: {check.actual_value:.3f} "
                        f"(target: {check.target_value:.2f})"
                    )

        # Top 3 failures
        top_failures = self.get_top_failures(3)
        if top_failures:
            print("\n🔴 Top Failures (lowest scores):")
            for i, failure in enumerate(top_failures, 1):
                print(f"   {i}. [{failure.scenario_id}] {failure.evaluator}/{failure.criterion}")
                print(f"      Score: {failure.score:.2f} | {failure.feedback[:80]}...")
                if failure.langsmith_url:
                    print(f"      Trace: {failure.langsmith_url}")

        print("\n" + "-" * 70)
        print("📁 Full report: e2e_results/diagnostic_report.json")
        print("📄 Markdown: e2e_results/failed_scenarios.md")
        print("=" * 70 + "\n")


class DiagnosticCollector:
    """
    Collects diagnostic data throughout a test session.

    This is used as a global singleton to collect data across all tests,
    then generate the final report.
    """

    def __init__(self):
        self.report = DiagnosticReport()
        self._current_test: Optional[str] = None
        self._test_start_time: float = 0.0

    def configure(
        self,
        project_name: str = "",
        endpoint: str = "",
    ) -> None:
        """Configure the collector with session metadata."""
        self.report.project_name = project_name
        self.report.langsmith_endpoint = endpoint

    def start_test(self, test_name: str) -> None:
        """Mark the start of a test."""
        import time

        self._current_test = test_name
        self._test_start_time = time.time()

    def record_outcome(
        self,
        scenario_id: str,
        passed: bool,
        evaluator_scores: Optional[Dict[str, float]] = None,
        failures: Optional[List[DiagnosticFailure]] = None,
        run_ids: Optional[List[str]] = None,
        total_tokens: int = 0,
        total_llm_calls: int = 0,
        total_llm_time_ms: float = 0.0,
    ) -> None:
        """Record the outcome of the current test."""
        import time

        duration = time.time() - self._test_start_time

        # Generate LangSmith URLs for failures
        if failures and run_ids:
            for failure in failures:
                if not failure.langsmith_url and run_ids:
                    failure.langsmith_run_id = run_ids[0] if run_ids else None
                    if failure.langsmith_run_id:
                        failure.langsmith_url = generate_langsmith_url(
                            failure.langsmith_run_id,
                            self.report.project_name,
                            self.report.langsmith_endpoint,
                        )

        outcome = TestOutcome(
            test_name=self._current_test or "unknown",
            scenario_id=scenario_id,
            passed=passed,
            duration_seconds=duration,
            evaluator_scores=evaluator_scores or {},
            failures=failures or [],
            run_ids=run_ids or [],
            total_tokens=total_tokens,
            total_llm_calls=total_llm_calls,
            total_llm_time_ms=total_llm_time_ms,
        )

        self.report.add_outcome(outcome)

    def record_execution_error(
        self,
        scenario_id: str,
        error_type: str,
        error_message: str,
        traceback: Optional[str] = None,
    ) -> None:
        """Record an execution error (not an evaluation failure)."""
        failure = DiagnosticFailure(
            test_name=self._current_test or "unknown",
            scenario_id=scenario_id,
            evaluator="execution",
            criterion="scenario_execution",
            score=0.0,
            feedback=error_message,
            category=FailureCategory.EXECUTION_ERROR,
            error_type=error_type,
            error_message=error_message,
            traceback=traceback,
        )

        self.record_outcome(
            scenario_id=scenario_id,
            passed=False,
            failures=[failure],
        )

    def set_graph_stats(self, graph_stats: Dict[str, Any]) -> None:
        """Set aggregated graph stats and run threshold checks."""
        self.report.set_graph_stats(graph_stats)

    def export(self, output_dir: str = "e2e_results") -> Dict[str, str]:
        """
        Export the diagnostic report to files.

        Returns:
            Dict with paths to exported files
        """
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)

        # Export JSON
        json_path = output_path / "diagnostic_report.json"
        json_path.write_text(self.report.to_json())

        # Export Markdown
        md_path = output_path / "failed_scenarios.md"
        md_path.write_text(self.report.to_markdown())

        return {
            "json": str(json_path),
            "markdown": str(md_path),
        }

    def print_summary(self) -> None:
        """Print the console summary."""
        self.report.print_console_summary()


# Global collector instance for use across tests
_diagnostic_collector: Optional[DiagnosticCollector] = None


def get_diagnostic_collector() -> DiagnosticCollector:
    """Get or create the global diagnostic collector."""
    global _diagnostic_collector
    if _diagnostic_collector is None:
        _diagnostic_collector = DiagnosticCollector()
    return _diagnostic_collector


def reset_diagnostic_collector() -> None:
    """Reset the global diagnostic collector (for testing)."""
    global _diagnostic_collector
    _diagnostic_collector = None


def extract_failures_from_reports(
    evaluation_reports: Dict[str, Any],
    test_name: str,
    scenario_id: str,
    run_ids: Optional[List[str]] = None,
    project_name: Optional[str] = None,
    endpoint: Optional[str] = None,
    trace_summary: Optional[Any] = None,
) -> List[DiagnosticFailure]:
    """
    Extract DiagnosticFailure objects from evaluation reports.

    Args:
        evaluation_reports: Dict mapping evaluator names to EvaluationReport objects
        test_name: The pytest test name
        scenario_id: The scenario identifier
        run_ids: List of LangSmith run IDs for trace linking
        project_name: LangSmith project name for URL generation
        endpoint: LangSmith endpoint for URL generation
        trace_summary: Optional TraceSummary with enriched trace data

    Returns:
        List of DiagnosticFailure objects for failed criteria
    """
    failures = []

    # Extract context from trace_summary if available
    transcript_context = {}
    if trace_summary is not None:
        # Build transcript context indexed by turn number for failure context
        if hasattr(trace_summary, "transcript"):
            for entry in trace_summary.transcript:
                turn = entry.turn_number if hasattr(entry, "turn_number") else 0
                if turn not in transcript_context:
                    transcript_context[turn] = {"user": None, "assistant": None}
                if hasattr(entry, "role"):
                    if entry.role == "user":
                        transcript_context[turn]["user"] = entry.content
                    else:
                        transcript_context[turn]["assistant"] = entry.content

    for evaluator_name, report in evaluation_reports.items():
        # Handle both EvaluationReport objects and dicts
        if hasattr(report, "results"):
            results = report.results
        elif isinstance(report, dict):
            results = report.get("results", [])
        else:
            continue

        for result in results:
            # Handle both EvaluationResult objects and dicts
            if hasattr(result, "passed"):
                passed = result.passed
                criterion = result.criterion
                score = result.score
                feedback = result.feedback
                details = result.details if hasattr(result, "details") else {}
            elif isinstance(result, dict):
                passed = result.get("passed", True)
                criterion = result.get("criterion", "unknown")
                score = result.get("score", 0.0)
                feedback = result.get("feedback", "")
                details = result.get("details", {})
            else:
                continue

            if not passed:
                # Categorize the failure
                category = FailureCategorizer.categorize(evaluator_name, criterion)

                # Generate LangSmith URL if run_ids available
                langsmith_run_id = run_ids[0] if run_ids else None
                langsmith_url = None
                if langsmith_run_id:
                    langsmith_url = generate_langsmith_url(
                        langsmith_run_id,
                        project_name,
                        endpoint,
                    )

                # Extract turn context if available in details or trace_summary
                turn_number = details.get("turn_number") if isinstance(details, dict) else None
                user_message = None
                assistant_response = None
                trip_inputs_at_failure = None

                # Try to get context from trace_summary
                if trace_summary is not None:
                    # Get last turn context if no specific turn mentioned
                    if turn_number is None and transcript_context:
                        turn_number = max(transcript_context.keys())

                    if turn_number and turn_number in transcript_context:
                        user_message = transcript_context[turn_number].get("user")
                        assistant_response = transcript_context[turn_number].get("assistant")

                    # Get trip inputs at failure
                    if hasattr(trace_summary, "final_trip_inputs"):
                        trip_inputs_at_failure = trace_summary.final_trip_inputs

                failure = DiagnosticFailure(
                    test_name=test_name,
                    scenario_id=scenario_id,
                    evaluator=evaluator_name,
                    criterion=criterion,
                    score=score,
                    feedback=feedback,
                    category=category,
                    turn_number=turn_number,
                    user_message=user_message,
                    assistant_response=assistant_response,
                    trip_inputs_at_failure=trip_inputs_at_failure,
                    langsmith_run_id=langsmith_run_id,
                    langsmith_url=langsmith_url,
                )
                failures.append(failure)

    return failures


def record_evaluation_outcome(
    test_name: str,
    scenario_id: str,
    evaluation_reports: Dict[str, Any],
    run_ids: Optional[List[str]] = None,
    trace_summary: Optional[Any] = None,
    total_tokens: int = 0,
    total_llm_calls: int = 0,
    total_llm_time_ms: float = 0.0,
    conversation_result: Optional[Any] = None,
) -> None:
    """
    Convenience function to record an evaluation outcome to the global collector.

    Args:
        test_name: The pytest test name
        scenario_id: The scenario identifier
        evaluation_reports: Dict mapping evaluator names to EvaluationReport objects
        run_ids: List of LangSmith run IDs for trace linking
        trace_summary: Optional TraceSummary with enriched trace data for context
        total_tokens: Total tokens used across all turns (overridden by
            conversation_result if provided)
        total_llm_calls: Total LLM calls made across all turns (overridden by
            conversation_result if provided)
        total_llm_time_ms: Total LLM time in milliseconds (overridden by
            conversation_result if provided)
        conversation_result: Optional ConversationResult to auto-extract metrics from
    """
    # Auto-extract metrics from conversation_result if provided
    if conversation_result is not None:
        total_tokens = getattr(conversation_result, "total_tokens", 0) or total_tokens
        total_llm_calls = getattr(conversation_result, "total_llm_calls", 0) or total_llm_calls
        total_llm_time_ms = (
            getattr(conversation_result, "total_llm_time_ms", 0.0) or total_llm_time_ms
        )

    collector = get_diagnostic_collector()

    # Extract evaluator scores
    evaluator_scores = {}
    all_passed = True

    for evaluator_name, report in evaluation_reports.items():
        if hasattr(report, "overall_score"):
            evaluator_scores[evaluator_name] = report.overall_score
            if hasattr(report, "overall_passed") and not report.overall_passed:
                all_passed = False
        elif isinstance(report, dict):
            evaluator_scores[evaluator_name] = report.get("overall_score", 0.0)
            if not report.get("overall_passed", True):
                all_passed = False

    # Extract failures with trace context
    failures = extract_failures_from_reports(
        evaluation_reports=evaluation_reports,
        test_name=test_name,
        scenario_id=scenario_id,
        run_ids=run_ids,
        project_name=collector.report.project_name,
        endpoint=collector.report.langsmith_endpoint,
        trace_summary=trace_summary,
    )

    # Record to collector
    collector.record_outcome(
        scenario_id=scenario_id,
        passed=all_passed,
        evaluator_scores=evaluator_scores,
        failures=failures,
        run_ids=run_ids,
        total_tokens=total_tokens,
        total_llm_calls=total_llm_calls,
        total_llm_time_ms=total_llm_time_ms,
    )
