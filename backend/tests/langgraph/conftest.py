"""Conftest for langgraph tests.

Provides:
- Automatic cache clearing (inherited from parent conftest.py)
- Prompt-to-stub coverage validation
"""

from __future__ import annotations

from pathlib import Path

import pytest

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
        "_suggested_responses",
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
    # Condense
    "condense": "Message condenser",
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
