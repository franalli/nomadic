"""LLM-judge smoke tests - run before demos or after prompt changes.

These tests:
- Use REAL LLM calls (not mocked)
- Run manually or before demos (NOT for PR gating)
- Have loose thresholds - just "no obvious violation"
- Skip if OPENAI_API_KEY is not set

Run with: OPENAI_API_KEY=sk-... pytest -m llm_smoke -v

NOT for PR gating - use `pytest -m "e2e and not llm_smoke"` for PR checks.
"""

from __future__ import annotations

import json
import os
import re

import pytest

from tests.langgraph.e2e_helpers import dump_failure, run_multi_turn
from tests.langgraph.fixtures import FUTURE_DATE


def skip_without_api_key():
    """Skip test if OPENAI_API_KEY is not set."""
    if not os.getenv("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY not set - skipping LLM smoke test")


def extract_json(text: str) -> dict:
    """Tolerant JSON extraction - find first {...} block.

    Handles cases where LLM returns extra text around JSON.
    """
    # Try direct parse first
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Find first JSON object (simple heuristic)
    match = re.search(r"\{[^{}]*\}", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    # Return empty dict with error flag
    return {"_parse_error": True, "_raw": text[:200]}


@pytest.mark.e2e
@pytest.mark.llm_smoke
class TestLLMSmoke:
    """Smoke tests with real LLM - loose thresholds, run before demos.

    These tests verify basic constraint handling and clarification behavior.
    They use real LLM calls and should NOT be used for PR gating.
    """

    @pytest.mark.asyncio
    async def test_constraint_not_obviously_violated(self):
        """Budget constraint mentioned → not obviously violated in response.

        This test checks that:
        1. Hard invariant: No luxury keywords in a budget trip response
        2. Soft check: LLM judge agrees budget is respected
        """
        skip_without_api_key()

        result, turns = await run_multi_turn(
            [
                "I want a budget trip to Europe, only $500 total",
                f"From {FUTURE_DATE} for 1 week",
                "Solo traveler",
            ]
        )

        response = result.get("assistant_message") or ""
        failures = []

        # HARD INVARIANT: no luxury keywords in budget trip
        luxury_signals = [
            "five-star",
            "5-star",
            "luxury suite",
            "premium suite",
            "first class",
            "private jet",
            "michelin star",
        ]
        for sig in luxury_signals:
            if sig.lower() in response.lower():
                failures.append(f"Budget trip mentions '{sig}'")

        # LLM JUDGE (only if no hard failures and response exists)
        if not failures and response:
            from app.plan_graph import call_llm_with_timeout

            try:
                judgment_raw = await call_llm_with_timeout(
                    model="small",
                    prompt=f"""Does this travel response respect a $500 budget constraint?
The response should not suggest expensive options that would exceed $500 total.

RESPONSE:
{response[:1500]}

Return JSON only: {{"respects_budget": true, "reason": "brief explanation"}}
or {{"respects_budget": false, "reason": "what violates budget"}}""",
                    timeout_seconds=30.0,
                    max_tokens=150,
                    temperature=0.0,
                )
                judgment = extract_json(judgment_raw)

                if judgment.get("_parse_error"):
                    failures.append(f"LLM judge returned non-JSON: {judgment.get('_raw')}")
                elif not judgment.get("respects_budget", True):
                    failures.append(f"LLM judge: {judgment.get('reason', 'budget violated')}")

            except Exception as e:
                failures.append(f"LLM judge call failed: {e}")

        if failures:
            path = dump_failure("test_constraint_smoke", turns, failures, result)
            pytest.fail(f"Constraint smoke test failed. Artifact: {path}")

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="Constraint conflict detection not yet implemented - "
        "system proceeds with field collection"
    )
    async def test_conflicting_constraints_asks_clarification(self):
        """Conflicting constraints → asks for clarification, doesn't just pick one.

        When user requests luxury + low budget, the system should ask for clarification
        rather than silently ignoring one constraint.

        NOTE: This test is currently xfail because the system doesn't yet detect
        constraint conflicts at the extraction phase. It proceeds with standard
        field collection instead of surfacing the luxury/budget conflict.
        """
        skip_without_api_key()

        result, turns = await run_multi_turn(
            [
                "I want luxury 5-star hotels but my budget is only $200 total",
            ]
        )

        response = result.get("assistant_message") or ""
        failures = []

        # HARD INVARIANT: should contain a question mark OR clarification language
        has_question = "?" in response

        clarification_signals = [
            "clarify",
            "which",
            "prefer",
            "priority",
            "help me understand",
            "could you",
            "would you",
            "budget or",
            "either",
            "trade-off",
            "challenge",
            "difficult",
        ]
        has_clarification = any(sig.lower() in response.lower() for sig in clarification_signals)

        if not has_question and not has_clarification:
            failures.append(
                "No question or clarification language - system just picked one option "
                "instead of asking about the conflict"
            )

        if failures:
            path = dump_failure("test_clarification_smoke", turns, failures, result)
            pytest.fail(f"Clarification smoke test failed. Artifact: {path}")
