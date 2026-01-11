"""
GateEvaluator - Centralized gate evaluation for routing decisions.

This module contains the refactored GateEvaluator that uses extracted gate classes.
All routing gates are evaluated here in priority order.

Usage:
    from app.planner.gates import GateEvaluator
    result = GateEvaluator.evaluate(state)
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from app.debug_utils import _debug
from app.planner.gates.base import Gate, GateContext

# Import all gate implementations
# Note: Consolidated gates (removed):
#   - HighConfidenceGate (100) -> removed, READY_NO_FIELDS handles core_complete
#   - KeywordHeuristicGate (120) -> merged into QuestionKeywordGate
#   - StrategyPreCoreValueWithDestGate (85) -> merged into StrategyPreCoreValueGate
from app.planner.gates.implementations import (
    CoreCollectionGate,
    FastPathGate,
    GenerateRequestedGate,
    InfeasibilityGate,
    QuestionKeywordGate,
    ReadyNoFieldsGate,
    RouterLLMGate,
    ShortCircuitGate,
    SpecialistPreCoreGate,
    StrategyExpansionGate,
    StrategyPostCoreGate,
    StrategyPreCoreValueGate,
    StrategyTopicSwitchGate,
)
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.readiness import compute_trip_readiness
from app.planner.gates.result import GateResult
from app.planner.gates.topic_detection import detect_strategy_topic

if TYPE_CHECKING:
    from app.plan_graph import GraphState, TripInputs

# Re-export for backward compatibility
from app.known_places import is_known_place
from app.pattern_matching import (
    INTENT_ONLY_KEYWORDS,
    QUESTION_WORDS,
    is_text_date_compatible,
)
from app.planner.gates.keyword_utils import keyword_match
from app.planner.gates.topic_detection import ALL_STRATEGY_KEYWORDS


class GateEvaluator:
    """
    Centralized gate evaluator for routing decisions.

    All routing gates are evaluated here in priority order.
    Nodes should read the GateResult from state rather than re-deriving conditions.
    """

    # Class-level aliases for backward compatibility with tests
    QUESTION_WORDS = QUESTION_WORDS
    INTENT_ONLY_KEYWORDS = INTENT_ONLY_KEYWORDS

    # Gate registry - ordered by precedence (lowest number = highest priority)
    # Consolidated from 16 to 13 gates:
    #   - Removed: StrategyPreCoreValueWithDestGate (85) -> merged into 80
    #   - Removed: HighConfidenceGate (100) -> READY_NO_FIELDS handles core_complete
    #   - Removed: KeywordHeuristicGate (120) -> merged into QuestionKeywordGate
    _gates: List[Gate] = [
        StrategyExpansionGate(),  # 10
        GenerateRequestedGate(),  # 20
        ShortCircuitGate(),  # 30
        InfeasibilityGate(),  # 30 (same precedence as SHORT_CIRCUIT)
        StrategyPostCoreGate(),  # 35: Stage 1 trigger after core complete
        ReadyNoFieldsGate(),  # 40
        FastPathGate(),  # 50
        SpecialistPreCoreGate(),  # 60
        StrategyTopicSwitchGate(),  # 70
        StrategyPreCoreValueGate(),  # 80 (now handles both with/without destinations)
        CoreCollectionGate(),  # 90
        QuestionKeywordGate(),  # 110 (now includes keyword heuristic fallback)
        RouterLLMGate(),  # 999 (default fallback)
    ]

    @classmethod
    def evaluate(cls, state: "GraphState") -> GateResult:
        """
        Evaluate all gates and return the result.

        This is the ONLY place where routing decisions should be made.
        Gate results are cached for efficiency when the same state is encountered.

        Args:
            state: Current graph state

        Returns:
            GateResult with gate_fired, destination, and metadata
        """
        start_time = time.perf_counter()
        user_text = state.user_text or ""

        # Try cache first
        cache_result = cls._try_gate_cache(state, user_text)
        if cache_result is not None:
            cache_key, cached_result = cache_result
            if cached_result is not None:
                # Update state metadata to indicate cache hit
                state.metadata["gate_cache_hit"] = True
                return cached_result
        else:
            cache_key = None

        # Determine if we should prefer dates over destinations
        user_text_lower = user_text.lower()
        ti = state.trip_inputs

        # PRE-COMPUTE STRATEGY TOPIC ONCE (avoids 4+ redundant calls in gates)
        detected_topic = detect_strategy_topic(user_text_lower, ti.activity_settings)

        # Use pre-computed topic for prefer_date_first check
        prefer_date_first = cls._should_prefer_date_first_with_topic(
            user_text_lower, ti, detected_topic
        )

        # Compute trip readiness
        readiness = compute_trip_readiness(
            ti, prefer_date_first=prefer_date_first, metadata=state.metadata
        )

        # Build context for gates (pass pre-computed topic)
        ctx = GateContext.from_state(
            state, readiness, start_time, detected_strategy_topic=detected_topic
        )

        # Evaluate gates in order
        skipped_gates: List[str] = []
        result: Optional[GateResult] = None

        for gate in cls._gates:
            result = gate.evaluate(ctx)
            if result is not None:
                # Gate fired - add skipped gates and finalize
                result = cls._finalize_result(result, skipped_gates, ctx, state)
                break
            skipped_gates.append(gate.name)

        # Should never reach here due to RouterLLMGate, but just in case
        if result is None:
            result = GateResult(
                gate_fired=GatePrecedence.ROUTER_LLM,
                destination="router",
                reason="fallback_no_gate_fired",
                eval_time_ms=ctx.elapsed_ms(),
                skipped_gates=skipped_gates,
            )

        # Cache the result
        if cache_key is not None:
            cls._cache_gate_result(cache_key, result)

        return result

    @classmethod
    def _finalize_result(
        cls,
        result: GateResult,
        skipped_gates: List[str],
        ctx: GateContext,
        state: "GraphState",
    ) -> GateResult:
        """Add final observability fields to the result."""
        # Late import to avoid circular dependency
        from app.plan_graph import _record_gate_latency

        eval_time_ms = ctx.elapsed_ms()
        _record_gate_latency(eval_time_ms)

        # Store gate trace in metadata for debugging
        if ctx.gate_trace:
            state.metadata["gate_trace"] = ctx.gate_trace
            _debug(
                "GATE_TRACE",
                gate_fired=(
                    result.gate_fired.name
                    if hasattr(result.gate_fired, "name")
                    else str(result.gate_fired)
                ),
                destination=result.destination,
                gates_checked=len(ctx.gate_trace),
                trace_summary=[
                    f"{g['gate']}:{'FIRED' if g['fired'] else 'skip'}" for g in ctx.gate_trace
                ],
            )

        # v5 observability fields
        lqa_reason = state.metadata.get("lqa_reason")
        llm_budget_used = state.metadata.get("llm_calls_this_turn", 0)
        date_clarify_mode = bool(state.metadata.get("date_clarify_mode", False))

        # Create updated result with all fields
        # Use detected strategy topic as fallback if gate didn't set one explicitly
        # This preserves the topic even when routing to required_fields
        final_strategy_topic = result.strategy_topic or ctx.detected_strategy_topic
        return GateResult(
            gate_fired=result.gate_fired,
            destination=result.destination,
            reason=result.reason,
            skipped_gates=skipped_gates,
            eval_time_ms=eval_time_ms,
            intent=result.intent,
            strategy_topic=final_strategy_topic,
            question_target=result.question_target,
            metadata_updates=result.metadata_updates,
            # v5 Routing Observability fields
            lqa_reason=lqa_reason,
            llm_budget_used=llm_budget_used,
            date_clarify_mode=date_clarify_mode,
        )

    @classmethod
    def _should_prefer_date_first_with_topic(
        cls, text_lower: str, ti: "TripInputs", detected_topic: Optional[str]
    ) -> bool:
        """
        Check if we should prefer asking about dates before destinations.

        Returns True when intent is broad (strategy topic detected) but no
        destination entities have been extracted. In these cases, asking about
        timing first helps provide better strategy recommendations.

        Args:
            text_lower: Lowercased user text
            ti: TripInputs
            detected_topic: Pre-computed strategy topic (avoids re-detection)
        """
        # If destinations already exist, use normal priority
        if ti.destinations:
            return False

        # Use pre-computed topic instead of re-detecting
        if detected_topic:
            _debug(
                "prefer_date_first: strategy topic detected without destinations",
                topic=detected_topic,
            )
            return True

        return False

    @classmethod
    def _should_prefer_date_first(cls, text_lower: str, ti: "TripInputs") -> bool:
        """
        Check if we should prefer asking about dates before destinations.

        DEPRECATED: Use _should_prefer_date_first_with_topic with pre-computed topic.
        Kept for backward compatibility with external callers.
        """
        detected_topic = detect_strategy_topic(text_lower, ti.activity_settings)
        return cls._should_prefer_date_first_with_topic(text_lower, ti, detected_topic)

    @classmethod
    def text_is_compatible_with_target(cls, user_text: str, question_target: Optional[str]) -> bool:
        """
        Check if user_text looks like an answer to the given question_target.

        This is used to determine if a user is answering a pending question
        (e.g., providing dates when question_target="dates") vs making a new
        request (e.g., topic switch).

        Args:
            user_text: The user's input text
            question_target: The current question target ("dates", "origin", etc.)

        Returns:
            True if the text appears to be answering the question_target
        """
        if not question_target or not user_text:
            return False

        text_lower = user_text.strip().lower()
        text_stripped = user_text.strip()

        if question_target in ("dates", "start_date"):
            # Delegate to consolidated date compatibility check
            return is_text_date_compatible(user_text)

        elif question_target == "origin":
            # Check if looks like a city/place name (capitalized, no strategy keywords)
            # Use keyword_match for pre-compiled regex efficiency
            if not keyword_match(text_lower, ALL_STRATEGY_KEYWORDS):
                # Simple heuristic: short input that's capitalized or known place
                if len(text_stripped) < 50 and (
                    text_stripped[0].isupper() or is_known_place(text_stripped)
                ):
                    return True

        elif question_target == "destinations":
            # Similar to origin but allow multiple places
            if is_known_place(text_stripped):
                return True

        elif question_target == "travelers":
            # Look for number patterns
            traveler_pattern = (
                r"\b("
                r"\d+|one|two|three|four|five|six|seven|eight|nine|ten|"
                r"couple|family|solo|alone|just me"
                r")\b"
            )
            if re.search(traveler_pattern, text_lower):
                return True

        elif question_target == "budget":
            # Look for currency/budget patterns
            if re.search(
                r"\b(\$|€|£|\d+|budget|cheap|luxury|mid-range|moderate|flexible)\b",
                text_lower,
            ):
                return True

        return False

    # =========================================================================
    # CACHE UTILITY METHODS
    # =========================================================================

    @classmethod
    def _hash_trip_inputs(cls, ti: "TripInputs") -> str:
        """Hash trip inputs for gate cache key."""
        trip_dict = {
            "destinations": sorted(ti.destinations or []),
            "origin": ti.origin,
            "start_date": ti.start_date,
            "end_date": ti.end_date,
            "adults": ti.adults,
            "budget": ti.budget,
        }
        return hashlib.md5(json.dumps(trip_dict, sort_keys=True).encode()).hexdigest()[:16]

    @classmethod
    def _hash_metadata(
        cls, metadata: Dict[str, Any], flags: Dict[str, Any], state: "GraphState"
    ) -> str:
        """Hash gate-determining metadata for cache key.

        Includes metadata, flags, and state fields that affect gate decisions.
        """
        meta_dict = {
            # Metadata fields
            "question_target": metadata.get("question_target"),
            "date_clarify_mode": metadata.get("date_clarify_mode", False),
            "has_blocking_errors": bool(metadata.get("date_blocking_errors")),
            "last_strategy_topic": metadata.get("last_strategy_topic"),
            "auto_fire_topic_switch": metadata.get("auto_fire_topic_switch"),
            "fast_path": metadata.get("fast_path"),
            "strategy_bootstrap_active": metadata.get("strategy_bootstrap_active"),
            # Flags
            "flags_fast_path": flags.get("fast_path"),
            "flags_strategy_bootstrap": flags.get("strategy_bootstrap_active"),
            # State fields that affect gates
            "pending_strategy_expansion": getattr(state, "pending_strategy_expansion", False),
            "strategy_expansion_tier": getattr(state, "strategy_expansion_tier", None),
        }
        return hashlib.md5(json.dumps(meta_dict, sort_keys=True).encode()).hexdigest()[:16]

    @classmethod
    def _try_gate_cache(
        cls, state: "GraphState", user_text: str
    ) -> Optional[Tuple[str, Optional[GateResult]]]:
        """Try to get gate result from cache.

        Returns:
            (cache_key, cached_result) if hit, (cache_key, None) if miss
        """
        from app.planner.cache import GateEvaluationCache

        session_id = state.metadata.get("session_id", "unknown")
        user_text_hash = hashlib.md5(user_text.lower().encode()).hexdigest()[:16]
        trip_inputs_hash = cls._hash_trip_inputs(state.trip_inputs)
        metadata_hash = cls._hash_metadata(state.metadata, state.flags or {}, state)

        cache = GateEvaluationCache.get_instance()
        cache_key = cache.compute_key(session_id, user_text_hash, trip_inputs_hash, metadata_hash)

        cached = cache.get(cache_key, state)
        if cached is not None:
            # Reconstruct GateResult from cached dict
            result = GateResult(
                gate_fired=GatePrecedence(cached["gate_fired"]),
                destination=cached["destination"],
                reason=cached["reason"],
                skipped_gates=cached.get("skipped_gates", []),
                eval_time_ms=cached.get("eval_time_ms", 0.0),
                intent=cached.get("intent"),
                strategy_topic=cached.get("strategy_topic"),
                question_target=cached.get("question_target"),
                metadata_updates=cached.get("metadata_updates", {}),
                lqa_reason=cached.get("lqa_reason"),
                llm_budget_used=cached.get("llm_budget_used", 0),
                date_clarify_mode=cached.get("date_clarify_mode", False),
            )
            _debug("gate_cache_hit", cache_key=cache_key[:16], gate=result.gate_fired.name)
            return (cache_key, result)

        return (cache_key, None)

    @classmethod
    def _cache_gate_result(cls, cache_key: str, result: GateResult) -> None:
        """Cache gate evaluation result."""
        from app.planner.cache import GateEvaluationCache

        cache = GateEvaluationCache.get_instance()
        cache.set(
            cache_key,
            {
                "gate_fired": result.gate_fired.value,
                "destination": result.destination,
                "reason": result.reason,
                "skipped_gates": result.skipped_gates,
                "eval_time_ms": result.eval_time_ms,
                "intent": result.intent,
                "strategy_topic": result.strategy_topic,
                "question_target": result.question_target,
                "metadata_updates": result.metadata_updates,
                "lqa_reason": result.lqa_reason,
                "llm_budget_used": result.llm_budget_used,
                "date_clarify_mode": result.date_clarify_mode,
            },
        )
