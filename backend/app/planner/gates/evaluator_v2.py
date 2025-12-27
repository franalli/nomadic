"""
GateEvaluator - Centralized gate evaluation for routing decisions.

This module contains the refactored GateEvaluator that uses extracted gate classes.
All routing gates are evaluated here in priority order.

Usage:
    from app.planner.gates import GateEvaluator
    result = GateEvaluator.evaluate(state)
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, List, Optional

from app.debug_utils import _debug
from app.planner.gates.base import Gate, GateContext

# Import all gate implementations
from app.planner.gates.implementations import (
    CoreCollectionGate,
    FastPathGate,
    GenerateRequestedGate,
    HighConfidenceGate,
    InfeasibilityGate,
    KeywordHeuristicGate,
    QuestionKeywordGate,
    ReadyNoFieldsGate,
    RouterLLMGate,
    ShortCircuitGate,
    SpecialistPreCoreGate,
    StrategyExpansionGate,
    StrategyPostCoreGate,
    StrategyPreCoreValueGate,
    StrategyPreCoreValueWithDestGate,
    StrategyTopicSwitchGate,
)
from app.planner.gates.precedence import GatePrecedence
from app.planner.gates.readiness import compute_trip_readiness
from app.planner.gates.result import GateResult
from app.planner.gates.topic_detection import detect_strategy_topic

if TYPE_CHECKING:
    from app.plan_graph import GraphState, TripInputs

# Re-export for backward compatibility
from app.pattern_matching import (
    INTENT_ONLY_KEYWORDS,
    QUESTION_WORDS,
)


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
        StrategyPreCoreValueGate(),  # 80
        StrategyPreCoreValueWithDestGate(),  # 85
        CoreCollectionGate(),  # 90
        HighConfidenceGate(),  # 100
        QuestionKeywordGate(),  # 110
        KeywordHeuristicGate(),  # 120
        RouterLLMGate(),  # 999 (default fallback)
    ]

    @classmethod
    def evaluate(cls, state: "GraphState") -> GateResult:
        """
        Evaluate all gates and return the result.

        This is the ONLY place where routing decisions should be made.

        Args:
            state: Current graph state

        Returns:
            GateResult with gate_fired, destination, and metadata
        """
        start_time = time.perf_counter()

        # Determine if we should prefer dates over destinations
        user_text = state.user_text or ""
        user_text_lower = user_text.lower()
        ti = state.trip_inputs
        prefer_date_first = cls._should_prefer_date_first(user_text_lower, ti)

        # Compute trip readiness
        readiness = compute_trip_readiness(
            ti, prefer_date_first=prefer_date_first, metadata=state.metadata
        )

        # Build context for gates
        ctx = GateContext.from_state(state, readiness, start_time)

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
        return GateResult(
            gate_fired=result.gate_fired,
            destination=result.destination,
            reason=result.reason,
            skipped_gates=skipped_gates,
            eval_time_ms=eval_time_ms,
            intent=result.intent,
            strategy_topic=result.strategy_topic,
            question_target=result.question_target,
            metadata_updates=result.metadata_updates,
            # v5 Routing Observability fields
            lqa_reason=lqa_reason,
            llm_budget_used=llm_budget_used,
            date_clarify_mode=date_clarify_mode,
        )

    @classmethod
    def _should_prefer_date_first(cls, text_lower: str, ti: "TripInputs") -> bool:
        """
        Check if we should prefer asking about dates before destinations.

        Returns True when intent is broad (strategy topic detected) but no
        destination entities have been extracted. In these cases, asking about
        timing first helps provide better strategy recommendations.
        """
        # If destinations already exist, use normal priority
        if ti.destinations:
            return False

        # Check if strategy topic is detected
        detected_topic = detect_strategy_topic(text_lower, ti.activity_settings)
        if detected_topic:
            _debug(
                "prefer_date_first: strategy topic detected without destinations",
                topic=detected_topic,
            )
            return True

        return False
