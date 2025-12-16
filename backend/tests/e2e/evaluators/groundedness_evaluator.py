"""
Groundedness evaluator for checking factual accuracy and hallucination detection.
"""

from __future__ import annotations

from typing import Any, Dict, List

from tests.e2e.evaluators.base_evaluator import (
    BaseEvaluator,
    EvaluationCriteria,
    EvaluationResult,
)
from tests.e2e.trace_summarizer import TraceSummary


class GroundednessEvaluator(BaseEvaluator):
    """Evaluates that responses are grounded in tool outputs with no hallucinations."""

    name = "groundedness_evaluator"
    description = """Evaluates:
- All facts traceable to user input or tool outputs
- No invented prices, dates, or availability
- No fabricated hotel/flight details
- Appropriate hedging when information is uncertain
- Clear distinction between facts and suggestions"""

    criteria = [EvaluationCriteria.GROUNDEDNESS]
    pass_threshold = 0.85  # Higher threshold - hallucinations erode user trust

    def get_evaluation_prompt(
        self,
        summary: TraceSummary,
        scenario_goal: str,
        scenario_constraints: Dict[str, Any],
    ) -> str:
        transcript = summary.get_transcript_text()

        # Format tool outputs
        tool_outputs_text = ""
        for output in summary.tool_outputs:
            tool_outputs_text += (
                f"- {output.node_name} (Turn {output.turn_number}): {output.output_type}\n"
            )
            if output.data:
                tool_outputs_text += f"  Data: {str(output.data)[:200]}...\n"

        # Format branches if any
        branches_text = ""
        if summary.final_branches:
            for i, branch in enumerate(summary.final_branches):
                branches_text += f"\nBranch {i+1}:\n"
                branches_text += f"  Label: {branch.get('label', 'N/A')}\n"
                branches_text += f"  Description: {branch.get('description', 'N/A')}\n"
        return (
            "Evaluate whether the assistant's responses are grounded in actual data "
            "or contain hallucinations.\n\n"
            "## Conversation Transcript\n"
            f"{transcript}\n\n"
            "## Tool Outputs Available\n"
            f"{tool_outputs_text or 'No tool outputs recorded'}\n\n"
            "## Generated Branches/Recommendations\n"
            f"{branches_text or 'No branches generated'}\n\n"
            "## Evaluation Criteria\n\n"
            "1. **factual_grounding** (0-1): Are all stated facts traceable to user input "
            "or tool outputs?\n"
            "   - Prices, dates, and availability should come from tools\n"
            "   - Destination information should be general knowledge or from tools\n"
            "   - No specific hotel/flight names invented without tool data\n\n"
            "2. **no_invented_details** (0-1): Does the assistant avoid inventing specific "
            "details?\n"
            "   - No made-up prices\n"
            "   - No fabricated flight times or hotel names\n"
            "   - No invented availability information\n\n"
            "3. **appropriate_hedging** (0-1): Does the assistant appropriately hedge "
            "uncertain information?\n"
            '   - Uses phrases like "typically", "usually", "you might find"\n'
            "   - Doesn't claim certainty without data\n"
            "   - Suggests checking/confirming when appropriate\n\n"
            "4. **source_clarity** (0-1): Is it clear what's a suggestion vs. confirmed "
            "fact?\n"
            "   - Recommendations clearly framed as suggestions\n"
            "   - Confirmed bookings clearly distinguished\n"
            "   - User understands what requires further verification\n\n"
            "Mark as FAIL (score < 0.5) if there are clear hallucinations of specific "
            "facts (prices, names, dates).\n"
        )

    def parse_evaluation_response(self, response: str) -> List[EvaluationResult]:
        return self._parse_standard_response(response)
