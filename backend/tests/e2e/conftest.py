"""
Pytest configuration for E2E tests.

Provides shared fixtures and configuration for all E2E test modules.
Includes diagnostic collection hooks for post-run analysis.
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from dotenv import load_dotenv

# Add backend to path
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

# Load .env file EARLY so pytestmark skipif conditions in test modules
# can see OPENAI_API_KEY before module-level skip decisions are made
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(BACKEND_DIR / ".env.docker", override=False)


def _create_diagnostic_collector():
    """Lazy-load the diagnostic collector factory when diagnostics are needed."""
    from tests.e2e.diagnostics import get_diagnostic_collector

    return get_diagnostic_collector()


# =============================================================================
# E2E Test Constants
# =============================================================================

# Use GPT-4o-mini for all E2E test LLM calls (scenario generation + evaluation)
# This reduces token costs by ~15-20x compared to GPT-4o
E2E_MODEL = os.getenv("E2E_TEST_MODEL", "gpt-4o-mini")


def pytest_configure(config):
    """Configure custom markers."""
    config.addinivalue_line("markers", "generated: mark test as generated scenario test")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "golden: mark test as golden replay test")
    config.addinivalue_line("markers", "asyncio: mark test as async")


def pytest_collection_modifyitems(config, items):
    """Modify test collection based on markers."""
    pass


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--langsmith-project",
        action="store",
        default="nomadic-e2e-tests",
        help="LangSmith project name for tracing",
    )
    parser.addoption(
        "--export-diagnostics",
        action="store_true",
        default=False,
        help="Export diagnostic report after test run",
    )
    parser.addoption(
        "--diagnostics-dir",
        action="store",
        default="e2e_results",
        help="Directory for diagnostic output files",
    )


# =============================================================================
# Shared Fixtures
# =============================================================================


@pytest.fixture(scope="session")
def langsmith_project(request):
    """
    Get LangSmith project name with timestamp for test isolation.

    Uses timestamped project names (e.g., nomadic-e2e-20251215-143052)
    to isolate CI runs from each other.
    """
    # Check if user provided a specific project name
    custom_project = request.config.getoption("--langsmith-project")
    if custom_project and custom_project != "nomadic-e2e-tests":
        return custom_project

    # Check environment variable
    env_project = os.getenv("LANGSMITH_PROJECT")
    if env_project:
        return env_project

    # Generate timestamped project name for isolation
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"nomadic-e2e-{timestamp}"


@pytest.fixture(scope="session")
def openai_api_key():
    """Get OpenAI API key."""
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        pytest.skip("OPENAI_API_KEY not set")
    return key


@pytest.fixture(scope="session")
def langsmith_api_key():
    """Get LangSmith API key."""
    return os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")


@pytest.fixture(scope="session")
def langsmith_endpoint():
    """Get LangSmith API endpoint (for EU region support)."""
    return os.getenv("LANGSMITH_ENDPOINT") or os.getenv("LANGCHAIN_ENDPOINT")


@pytest.fixture(scope="session", autouse=True)
def setup_environment(langsmith_project, langsmith_api_key, langsmith_endpoint):
    """Set up environment for E2E tests."""
    # Configure LangSmith if E2E tracing is enabled
    e2e_tracing = os.getenv("LANGSMITH_E2E_TRACING", "false").lower() == "true"
    if langsmith_api_key and e2e_tracing:
        os.environ["LANGCHAIN_API_KEY"] = langsmith_api_key
        os.environ["LANGCHAIN_TRACING_V2"] = "true"
        os.environ["LANGCHAIN_PROJECT"] = langsmith_project
        if langsmith_endpoint:
            os.environ["LANGCHAIN_ENDPOINT"] = langsmith_endpoint

    yield

    # Cleanup if needed


@pytest.fixture(scope="session")
def e2e_model():
    """Get the model to use for E2E tests (scenario generation + evaluation)."""
    return E2E_MODEL


# =============================================================================
# Fresh Start Fixture - Ensures Test Isolation
# =============================================================================


@pytest.fixture(autouse=True)
def fresh_start():
    """
    Clear ALL caches before and after each test for complete isolation.

    This fixture runs automatically for every test and ensures:
    - LLM response caches are cleared
    - Validation caches are cleared
    - MemorySaver checkpointer storage is cleared

    This prevents state leakage between tests that could cause:
    - Cached responses from one test affecting another
    - Destination confusion/hallucinations
    - Stale validation results
    """
    from app.plan_graph import clear_all_caches

    # Clear before test
    clear_all_caches()

    yield

    # Clear after test
    clear_all_caches()


@pytest.fixture(scope="session")
def langsmith_tracing_enabled(langsmith_api_key):
    """Check if LangSmith E2E tracing is enabled and configured."""
    return bool(langsmith_api_key) and os.getenv("LANGSMITH_E2E_TRACING", "false").lower() == "true"


@pytest.fixture
def temp_output_dir(tmp_path):
    """Create a temporary output directory for test results."""
    output_dir = tmp_path / "e2e_results"
    output_dir.mkdir(exist_ok=True)
    return str(output_dir)


# =============================================================================
# Test Result Tracking
# =============================================================================


class TestResultTracker:
    """Tracks test results for summary reporting."""

    def __init__(self):
        self.results = []

    def add_result(self, scenario_id: str, passed: bool, score: float, details: str = ""):
        self.results.append(
            {
                "scenario_id": scenario_id,
                "passed": passed,
                "score": score,
                "details": details,
            }
        )

    def get_summary(self) -> dict:
        if not self.results:
            return {"total": 0, "passed": 0, "failed": 0, "avg_score": 0}

        passed = sum(1 for r in self.results if r["passed"])
        total = len(self.results)
        avg_score = sum(r["score"] for r in self.results) / total

        return {
            "total": total,
            "passed": passed,
            "failed": total - passed,
            "avg_score": avg_score,
            "pass_rate": passed / total,
        }


@pytest.fixture(scope="module")
def result_tracker():
    """Shared result tracker for a test module."""
    return TestResultTracker()


# =============================================================================
# Async Test Support
# =============================================================================


@pytest.fixture(scope="session")
def event_loop_policy():
    """Use default event loop policy."""
    import asyncio

    return asyncio.DefaultEventLoopPolicy()


# =============================================================================
# Database Fixtures (if needed for E2E tests with persistence)
# =============================================================================


@pytest.fixture(scope="module")
def test_db_path(tmp_path_factory):
    """Create a temporary database for E2E tests."""
    return tmp_path_factory.mktemp("e2e_db") / "test.db"


@pytest.fixture
async def test_session(test_db_path):
    """Create a test database session."""
    # This can be expanded if E2E tests need database access
    yield None


# =============================================================================
# Pytest Hooks for Diagnostic Collection
# =============================================================================


def pytest_sessionstart(session):
    """Initialize diagnostic collection at session start."""
    collector = _create_diagnostic_collector()

    # Configure with LangSmith settings
    project = session.config.getoption("--langsmith-project", default="nomadic-e2e-tests")
    endpoint = os.getenv("LANGSMITH_ENDPOINT", "")

    collector.configure(project_name=project, endpoint=endpoint)


def pytest_runtest_setup(item):
    """Record test start time for duration tracking."""
    collector = _create_diagnostic_collector()
    collector.start_test(item.nodeid)


def pytest_sessionfinish(session, exitstatus):
    """
    Generate diagnostic report after all tests complete.

    This hook is called after all tests finish and prints a summary
    to console while exporting detailed reports to files.
    """
    collector = _create_diagnostic_collector()

    # Only print/export if we have results
    if collector.report.total_tests == 0:
        return

    # Always print console summary
    collector.print_summary()

    # Export if requested or if there are failures
    export_diagnostics = session.config.getoption("--export-diagnostics", default=False)
    has_failures = collector.report.failed_tests > 0

    if export_diagnostics or has_failures:
        diagnostics_dir = session.config.getoption("--diagnostics-dir", default="e2e_results")
        paths = collector.export(diagnostics_dir)
        print(f"📁 Diagnostic reports exported to: {paths['json']}")


# =============================================================================
# Diagnostic Fixture for Tests
# =============================================================================


@pytest.fixture
def diagnostic_collector():
    """Get the global diagnostic collector for recording test outcomes."""
    return _create_diagnostic_collector()


# =============================================================================
# Trace Enrichment
# =============================================================================


@pytest.fixture
def trace_enricher(langsmith_api_key, langsmith_endpoint):
    """
    Fixture that provides a trace enrichment function.

    When LangSmith is enabled, enriches TraceSummary with detailed trace data.
    When disabled, logs a debug message and returns the summary unchanged.
    """
    import logging

    from tests.e2e.trace_summarizer import TraceSummarizer

    logger = logging.getLogger(__name__)
    summarizer = TraceSummarizer()

    async def enrich(summary, run_ids):
        """
        Enrich a TraceSummary with LangSmith trace data.

        Args:
            summary: The TraceSummary to enrich
            run_ids: List of LangSmith run IDs to fetch

        Returns:
            Enriched TraceSummary (or original if LangSmith disabled)
        """
        if not langsmith_api_key:
            logger.debug("LangSmith tracing disabled, skipping trace enrichment")
            return summary

        if not run_ids:
            logger.debug("No run_ids provided, skipping trace enrichment")
            return summary

        try:
            enriched = await summarizer.enrich_summary_with_langsmith(
                summary=summary,
                run_ids=run_ids,
                api_key=langsmith_api_key,
                api_url=langsmith_endpoint,
            )
            return enriched
        except Exception as e:
            logger.warning(f"Failed to enrich trace: {e}")
            return summary

    return enrich


@pytest.fixture
def create_enriched_summary(langsmith_api_key, langsmith_endpoint):
    """
    Fixture that provides a function to create an enriched TraceSummary.

    This creates a local summary from ConversationResult and enriches it
    with LangSmith trace data when available. Use this fixture in tests
    to get a fully populated TraceSummary for evaluation.

    Usage:
        async def test_something(create_enriched_summary, conversation_executor, ...):
            result = await conversation_executor.execute_scenario(scenario)
            trace_summary = await create_enriched_summary(result)
            reports = await evaluators.evaluate(..., trace_summary=trace_summary)
    """
    import logging

    from tests.e2e.trace_summarizer import TraceSummarizer

    logger = logging.getLogger(__name__)
    summarizer = TraceSummarizer()

    async def create(result):
        """
        Create an enriched TraceSummary from a ConversationResult.

        Args:
            result: The ConversationResult from conversation execution

        Returns:
            TraceSummary enriched with LangSmith data (if available)
        """
        # Create local summary
        summary = summarizer.summarize_local(result)

        # Enrich with LangSmith data if available
        if langsmith_api_key and result.run_ids:
            try:
                summary = await summarizer.enrich_summary_with_langsmith(
                    summary=summary,
                    run_ids=result.run_ids,
                    api_key=langsmith_api_key,
                    api_url=langsmith_endpoint,
                )
            except Exception as e:
                logger.warning(f"Failed to enrich trace summary: {e}")

        return summary

    return create
