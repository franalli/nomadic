"""
Node-level evaluator for routing decisions and state transitions.
"""

from __future__ import annotations

from typing import Any, Dict, List

from tests.e2e.evaluators.base_evaluator import (
    BaseEvaluator,
    EvaluationCriteria,
    EvaluationResult,
)
from tests.e2e.trace_summarizer import TraceSummary


class NodeEvaluator(BaseEvaluator):
    """Evaluates node-level behavior: routing, state transitions, error handling."""

    name = "node_evaluator"
    description = """Evaluates:
- Correct routing decisions by the router node
- Valid state transitions between turns
- Tool input/output schema correctness
- Retry, fallback, and timeout behavior
- Proper error handling"""

    criteria = [
        EvaluationCriteria.ROUTING_ACCURACY,
        EvaluationCriteria.STATE_TRANSITION_VALIDITY,
        EvaluationCriteria.ERROR_HANDLING,
    ]
    pass_threshold = 0.75  # Technical correctness matters

    def get_evaluation_prompt(
        self,
        summary: TraceSummary,
        scenario_goal: str,
        scenario_constraints: Dict[str, Any],
    ) -> str:
        # Format routing decisions
        routing_text = ""
        for rd in summary.routing_decisions:
            routing_text += f"- Turn {rd.get('turn', '?')}: Intent={rd.get('intent', 'unknown')}"
            if rd.get("strategy_topic"):
                routing_text += f", Strategy={rd['strategy_topic']}"
            if rd.get("short_circuit"):
                routing_text += f", ShortCircuit={rd['short_circuit']}"
            if rd.get("confidence_routing"):
                routing_text += f", Confidence={rd['confidence_routing']}"
            routing_text += "\n"

        # Format state transitions
        transitions_text = ""
        for st in summary.state_transitions:
            transitions_text += f"- Turn {st.turn_number}: {st.field}: {st.before} → {st.after}"
            transitions_text += f" [{'VALID' if st.valid else 'INVALID'}]\n"

        # Format transcript
        transcript = summary.get_transcript_text()

        return f"""Evaluate the node-level behavior in this travel planning conversation.

## Conversation Transcript
{transcript}

## Routing Decisions
{routing_text or "No routing decisions recorded"}

## State Transitions
{transitions_text or "No state transitions recorded"}

## Errors Encountered
{summary.errors or "No errors"}

## Metrics
- Total LLM Calls: {summary.total_llm_calls}
- Cache Hits: {summary.total_cache_hits}
- Total Duration: {summary.total_duration_ms:.0f}ms

## Evaluation Criteria

1. **routing_accuracy** (0-1): Were routing decisions appropriate?
   - Did the router correctly identify user intent?
   - Were specialist nodes invoked when appropriate?
   - Was the short-circuit mechanism used correctly?
   - Were strategy topics identified when relevant?

2. **state_transitions** (0-1): Were state transitions valid and logical?
   - Did trip_inputs evolve correctly over turns?
   - No unexpected data loss between turns?
   - Additive information preserved?
   - Invalid state changes detected?

3. **error_handling** (0-1): Were errors handled appropriately?
   - Graceful degradation on failures?
   - Appropriate error messages to user?
   - Recovery from partial failures?
   - No silent failures?

4. **efficiency** (0-1): Was the system efficient?
   - Appropriate use of caching?
   - No unnecessary LLM calls?
   - Response times reasonable?

For routing_accuracy, consider:
- "required_fields" intent when missing essential info
- "flights"/"hotels"/"activities" when user asks specifically
- "strategy" when discussing activities like hiking, diving
- Short-circuit for simple acknowledgments or clarifications
"""

    def parse_evaluation_response(self, response: str) -> List[EvaluationResult]:
        return self._parse_standard_response(response)
