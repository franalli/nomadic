"""Conftest for langgraph tests.

Provides:
- Automatic cache clearing (inherited from parent conftest.py)
- Prompt-to-stub coverage validation
- Graph stats reset between tests
- Future date constants for tests
- Hermetic E2E fixture (FakeLLM for @pytest.mark.e2e tests)
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from app.plan_graph import reset_graph_stats
from tests.langgraph.fake_llm import FakeLLM


# =============================================================================
# Future Date Constants for Tests
# =============================================================================
# Tests should use these to avoid infeasibility detection for past dates
def get_future_date(days_ahead: int = 30) -> str:
    """Get an ISO date string for a future date."""
    return (date.today() + timedelta(days=days_ahead)).isoformat()


# Common future date constants (30 days ahead to avoid infeasibility)
FUTURE_DATE = get_future_date(30)  # e.g., "2026-01-18"
FUTURE_END_DATE = get_future_date(40)  # e.g., "2026-01-28"


@pytest.fixture(autouse=True)
def auto_reset_graph_stats():
    """Reset graph stats before each test to prevent pollution."""
    reset_graph_stats()
    yield
    # Optional: reset after test as well for cleaner state
    reset_graph_stats()


# =============================================================================
# Hermetic E2E Fixture (FakeLLM for @pytest.mark.e2e tests)
# =============================================================================


@pytest.fixture(autouse=True)
def hermetic_e2e_mode(request):
    """Force FakeLLM for E2E tests (except llm_smoke), ensuring no network calls.

    This fixture:
    - Auto-applies to all tests
    - For @pytest.mark.e2e tests (without llm_smoke): uses FakeLLM.patch_with_stub()
    - For @pytest.mark.llm_smoke tests: allows real LLM calls (skips if no API key)
    - For all other tests: no change (existing behavior)

    Acceptance criterion: `pytest -m "e2e and not llm_smoke"` never makes network calls.
    """
    markers = {m.name for m in request.node.iter_markers()}

    if "e2e" in markers and "llm_smoke" not in markers:
        # Hermetic E2E: force FakeLLM with deterministic stub responses
        with FakeLLM.patch_with_stub():
            yield
    else:
        # Non-E2E tests or llm_smoke tests: no FakeLLM patching
        yield


@pytest.fixture
def fake_llm_strict():
    """Explicit fixture for tests that want strict FakeLLM (fails on any LLM call)."""
    with FakeLLM.patch_strict() as config:
        yield config


# =============================================================================
# Prompt-Stub Coverage Validation
# =============================================================================

# Prompts that are partials (included by other prompts, not called directly)
_PARTIAL_PROMPTS = frozenset(
    [
        "_adapt_tone",
        "_json_output",
        "_markdown_rules",
        "_never_invent",
        "_scope_specialist",
        "_strategy_base",
    ]
)

# Prompts that are handled by pattern matching in llm_stub.py
# Maps prompt name -> the pattern/keyword in llm_stub.py that matches it
_STUB_PROMPT_HANDLERS = {
    # Router
    "router": "Role: Intent router",
    # Response polish
    "response_polish": "polished_message",
    # Specialists
    "flights": "SCOPE: FLIGHT PREFERENCES ONLY",
    "hotels": "SCOPE: HOTEL PREFERENCES ONLY",
    "activities": "SCOPE: ACTIVITY PREFERENCES ONLY",
    "transport": "SCOPE: TRANSPORT PREFERENCES ONLY",
    "correction": "SCOPE: CORRECTION",
    # Required fields (both variants)
    "required_fields": "Role: Experienced travel agent helping plan trips",
    "required_fields_confirm": "Role: Experienced travel agent helping plan trips",
    # Strategy prompts
    "strategy_hiking": "SCOPE: HIKING STRATEGY ONLY",
    "strategy_boating": "SCOPE:",  # Matched by generic strategy handler
    "strategy_diving": "SCOPE:",
    "strategy_skiing": "SCOPE:",
    "strategy_cycling": "SCOPE:",
    # Extractor
    "extractor": "EXTRACTION NODE",
    "extractor_light": "EXTRACTION NODE",  # Uses same handler as full extractor
    # Condense
    "condense": "Message condenser",
    # Missing fields guard
    "missing_fields_guard": "missing_fields_guard",
}


def _get_all_prompt_names() -> set[str]:
    """Get all prompt file names (without .txt extension) from prompts dir."""
    prompts_dir = Path(__file__).parents[2] / "app" / "prompts"
    if not prompts_dir.exists():
        return set()
    return {p.stem for p in prompts_dir.glob("*.txt")}


def _get_unmapped_prompts() -> list[str]:
    """Find prompts that don't have LLM stub handlers."""
    all_prompts = _get_all_prompt_names()
    unmapped = []
    for prompt_name in sorted(all_prompts):
        # Skip partials (they're included by other prompts, not called directly)
        if prompt_name in _PARTIAL_PROMPTS:
            continue
        # Check if we have a handler for this prompt
        if prompt_name not in _STUB_PROMPT_HANDLERS:
            unmapped.append(prompt_name)
    return unmapped


@pytest.fixture(scope="session")
def validate_prompt_stub_coverage():
    """Validate that all prompts have corresponding LLM stub handlers.

    This is a session-scoped fixture that can be requested by tests
    that want to verify stub coverage.
    """
    unmapped = _get_unmapped_prompts()
    return {
        "unmapped": unmapped,
        "all_prompts": _get_all_prompt_names(),
        "partial_prompts": _PARTIAL_PROMPTS,
        "handlers": _STUB_PROMPT_HANDLERS,
    }


def test_all_prompts_have_stub_handlers(validate_prompt_stub_coverage):
    """Ensure all non-partial prompts have LLM stub handlers defined.

    This test runs as part of the langgraph test suite to catch
    any new prompts that were added without corresponding stub handlers.
    """
    unmapped = validate_prompt_stub_coverage["unmapped"]
    if unmapped:
        pytest.fail(
            f"The following prompts do not have LLM stub handlers in "
            f"tests/llm_stub.py: {', '.join(unmapped)}\n\n"
            f"Add handlers to _STUB_PROMPT_HANDLERS in tests/langgraph/conftest.py "
            f"and implement the stub logic in tests/llm_stub.py"
        )
