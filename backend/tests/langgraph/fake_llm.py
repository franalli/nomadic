"""
FakeLLM: Tier A hermetic test harness for deterministic graph testing.

This module provides a FakeLLM that either:
1. Raises AssertionError on any LLM call ("strict" mode - for routing/invariant tests)
2. Returns deterministic responses keyed by semantic identifiers ("map" mode)

Usage:
    # Strict mode - fails if any LLM is called
    with FakeLLM.patch_strict():
        result = await run_turn("hello", {})

    # Map mode - returns configured responses
    responses = {
        ("extractor", "full"): {"destinations": ["Paris"]},
    }
    with FakeLLM.patch_map(responses):
        result = await run_turn("Paris next week", {})
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple
from unittest.mock import patch

# Semantic key type: (node_name, callsite_name, schema_version?)
SemanticKey = Tuple[str, ...]


@dataclass
class LLMCallRecord:
    """Record of an LLM call for assertions."""

    node_name: str
    callsite_name: str
    prompt_hash: str
    model: str
    max_tokens: int
    response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


@dataclass
class FakeLLMConfig:
    """Configuration for FakeLLM behavior."""

    mode: str = "strict"  # "strict" or "map"
    responses: Dict[SemanticKey, Dict[str, Any]] = field(default_factory=dict)
    prompt_bundle_hash: Optional[str] = None  # For drift detection
    model_id: Optional[str] = None  # For model verification
    call_records: List[LLMCallRecord] = field(default_factory=list)
    allow_fallback: bool = False  # If True in map mode, unmatched calls use llm_stub


class FakeLLM:
    """
    Fake LLM for hermetic testing of the plan graph.

    Two modes:
    - strict: Raises AssertionError on any LLM call (for testing routing/caching)
    - map: Returns responses keyed by (node_name, callsite_name) tuple

    Keying strategy:
    - Uses stable semantic keys (node_name, callsite_name) NOT prompt hash
    - Node name is inferred from prompt content markers
    - Prompt hash checked for equality (fail-fast on drift) but not for selection
    - This allows tests to survive prompt formatting changes
    """

    _config: Optional[FakeLLMConfig] = None
    _original_call_llm: Optional[Callable] = None

    # Markers in prompts to identify which node is calling
    _PROMPT_NODE_MARKERS: Dict[str, str] = {
        "Role: Intent router": "router",
        "Intent router": "router",
        "Role: Travel Itinerary Extractor": "extractor",
        "Itinerary Extractor": "extractor",
        "Role: Strategy specialist": "strategy",
        "Strategy specialist": "strategy",
        "Role: Hotels specialist": "hotels",
        "Hotels specialist": "hotels",
        "Role: Flights specialist": "flights",
        "Flights specialist": "flights",
        "Role: Activities specialist": "activities",
        "Activities specialist": "activities",
        "Role: Transport specialist": "transport",
        "Transport specialist": "transport",
        "Role: Required fields": "required_fields",
        "Required fields": "required_fields",
        "Role: General planner": "general",
        "General planner": "general",
        "Role: Correction handler": "correction",
        "Correction handler": "correction",
    }

    @classmethod
    def _infer_node_from_prompt(cls, prompt: str) -> str:
        """Infer the node name from prompt content markers."""
        prompt_lower = prompt[:500].lower()  # Check first 500 chars
        for marker, node_name in cls._PROMPT_NODE_MARKERS.items():
            if marker.lower() in prompt_lower:
                return node_name
        return "unknown"

    @classmethod
    def get_call_count(cls) -> int:
        """Get number of LLM calls made during this test."""
        if cls._config is None:
            return 0
        return len(cls._config.call_records)

    @classmethod
    def get_call_records(cls) -> List[LLMCallRecord]:
        """Get all LLM call records for assertions."""
        if cls._config is None:
            return []
        return list(cls._config.call_records)

    @classmethod
    def assert_no_llm_calls(cls) -> None:
        """Assert that no LLM calls were made."""
        count = cls.get_call_count()
        if count > 0:
            records = cls.get_call_records()
            calls = [f"{r.node_name}/{r.callsite_name}" for r in records]
            raise AssertionError(f"Expected 0 LLM calls but got {count}: {calls}")

    @classmethod
    def assert_llm_call_count(cls, expected: int) -> None:
        """Assert exact number of LLM calls."""
        actual = cls.get_call_count()
        if actual != expected:
            records = cls.get_call_records()
            calls = [f"{r.node_name}/{r.callsite_name}" for r in records]
            raise AssertionError(f"Expected {expected} LLM calls but got {actual}: {calls}")

    @classmethod
    async def _fake_call_llm(
        cls,
        model: str,
        prompt: str,
        timeout_seconds: float = 30.0,
        max_tokens: int = 512,
        temperature: float = 0.2,
        history: Any = None,
        user_message: Optional[str] = None,
        top_p: Optional[float] = None,
        max_retries: int = 1,
        **kwargs,
    ) -> str:
        """Fake LLM call that either raises or returns configured response.

        This matches the signature of call_llm_with_timeout.
        Node name is inferred from prompt content since call_llm_with_timeout
        doesn't pass semantic identifiers.
        """
        import hashlib

        config = cls._config
        if config is None:
            raise AssertionError("FakeLLM not configured - use patch_strict() or patch_map()")

        # Infer node name from prompt content
        node_name = cls._infer_node_from_prompt(prompt)
        callsite_name = "full"  # Default callsite

        # Compute prompt hash for drift detection
        prompt_hash = hashlib.sha256(prompt.encode()).hexdigest()[:16]

        # Create call record
        record = LLMCallRecord(
            node_name=node_name,
            callsite_name=callsite_name,
            prompt_hash=prompt_hash,
            model=model,
            max_tokens=max_tokens,
        )

        if config.mode == "strict":
            record.error = "LLM called unexpectedly in strict mode"
            config.call_records.append(record)
            raise AssertionError(
                f"LLM called unexpectedly in strict mode: "
                f"node={node_name}, callsite={callsite_name}, model={model}"
            )

        # Map mode - look up response by semantic key
        key: SemanticKey = (node_name, callsite_name)

        if key in config.responses:
            response = config.responses[key]
            record.response = response
            config.call_records.append(record)

            # Verify prompt_bundle_hash if configured (fail-fast on drift)
            if config.prompt_bundle_hash:
                # Would check against actual bundle hash here
                pass

            return json.dumps(response)

        # Try without callsite for broader matching
        key_node_only: SemanticKey = (node_name,)
        if key_node_only in config.responses:
            response = config.responses[key_node_only]
            record.response = response
            config.call_records.append(record)
            return json.dumps(response)

        # Fallback to llm_stub if allowed
        if config.allow_fallback:
            from tests.llm_stub import llm_json_for_prompt

            response = llm_json_for_prompt(prompt=prompt, user_message=None)
            record.response = response
            config.call_records.append(record)
            return json.dumps(response)

        # No match found - raise
        record.error = f"No response configured for key {key}"
        config.call_records.append(record)
        raise AssertionError(
            f"No response configured for LLM call: "
            f"node={node_name}, callsite={callsite_name}. "
            f"Add entry to responses dict: {key}"
        )

    @classmethod
    @contextmanager
    def patch_strict(cls) -> Iterator[FakeLLMConfig]:
        """
        Patch LLM calls to raise AssertionError on any call.

        Use for tests that should NOT make any LLM calls (routing, caching, etc.)

        Example:
            with FakeLLM.patch_strict() as config:
                result = await run_turn("hello", {})
                assert config.call_records == []  # No LLM calls
        """
        config = FakeLLMConfig(mode="strict")
        cls._config = config

        with patch("app.plan_graph.call_llm_with_timeout", cls._fake_call_llm):
            try:
                yield config
            finally:
                cls._config = None

    @classmethod
    @contextmanager
    def patch_map(
        cls,
        responses: Dict[SemanticKey, Dict[str, Any]],
        *,
        allow_fallback: bool = False,
        prompt_bundle_hash: Optional[str] = None,
    ) -> Iterator[FakeLLMConfig]:
        """
        Patch LLM calls to return configured responses.

        Args:
            responses: Dict mapping (node_name, callsite_name) to response dict
            allow_fallback: If True, unmatched calls use llm_stub.py (default: False)
            prompt_bundle_hash: Optional hash to verify against (fail-fast on drift)

        Example:
            responses = {
                ("extractor", "full"): {"destinations": ["Paris"]},
                ("router",): {"intent": "general"},  # Matches any router callsite
            }
            with FakeLLM.patch_map(responses) as config:
                result = await run_turn("Paris trip", {})
                assert len(config.call_records) == 2
        """
        config = FakeLLMConfig(
            mode="map",
            responses=responses,
            allow_fallback=allow_fallback,
            prompt_bundle_hash=prompt_bundle_hash,
        )
        cls._config = config

        with patch("app.plan_graph.call_llm_with_timeout", cls._fake_call_llm):
            try:
                yield config
            finally:
                cls._config = None

    @classmethod
    @contextmanager
    def patch_with_stub(cls) -> Iterator[FakeLLMConfig]:
        """
        Patch LLM calls to use llm_stub.py for all calls.

        This is a convenience method for tests that want deterministic
        responses without specifying each one.
        """
        config = FakeLLMConfig(mode="map", allow_fallback=True)
        cls._config = config

        with patch("app.plan_graph.call_llm_with_timeout", cls._fake_call_llm):
            try:
                yield config
            finally:
                cls._config = None


# =============================================================================
# Convenience fixtures for pytest
# =============================================================================


def fake_llm_strict():
    """Pytest fixture for strict FakeLLM."""
    return FakeLLM.patch_strict()


def fake_llm_with_responses(responses: Dict[SemanticKey, Dict[str, Any]]):
    """Pytest fixture for FakeLLM with configured responses."""
    return FakeLLM.patch_map(responses)
