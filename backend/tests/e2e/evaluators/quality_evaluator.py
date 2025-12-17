"""
Quality evaluator for conversation usefulness, clarity, and structure.
"""

from __future__ import annotations

from typing import Any, Dict, List

from tests.e2e.config import get_threshold
from tests.e2e.evaluators.base_evaluator import (
    BaseEvaluator,
    EvaluationCriteria,
    EvaluationResult,
)
from tests.e2e.trace_summarizer import TraceSummary


class QualityEvaluator(BaseEvaluator):
    """Evaluates overall conversation quality and usefulness."""

    name = "quality_evaluator"
    description = """Evaluates:
- Response usefulness and helpfulness
- Output clarity and structure
- Natural conversation flow
- Appropriate level of detail
- Professional tone and formatting"""

    criteria = [
        EvaluationCriteria.OUTPUT_CLARITY,
        EvaluationCriteria.GOAL_COMPLETION,
    ]
    pass_threshold = get_threshold("quality")

    def get_evaluation_prompt(
        self,
        summary: TraceSummary,
        scenario_goal: str,
        scenario_constraints: Dict[str, Any],
    ) -> str:

        transcript = summary.get_transcript_text()

        return (
            "Evaluate the quality of this travel planning conversation.\n\n"
            "## Scenario Goal\n"
            f"{scenario_goal or 'General travel planning assistance'}\n\n"
            "## Conversation Transcript\n"
            f"{transcript}\n\n"
            "## Final Extracted Information\n"
            f"- Destinations: {summary.final_trip_inputs.get('destinations', [])}\n"
            f"- Origin: {summary.final_trip_inputs.get('origin', 'Not specified')}\n"
            "- Dates: "
            f"{summary.final_trip_inputs.get('start_date', 'Not specified')} "
            "to "
            f"{summary.final_trip_inputs.get('end_date', 'Not specified')}\n\n"
            "## Evaluation Criteria\n\n"
            "1. **response_usefulness** (0-1): Are the assistant's responses helpful and "
            "actionable?\n"
            "   - Does the assistant provide relevant travel information?\n"
            "   - Are suggestions practical and appropriate?\n"
            "   - Does the assistant guide the user effectively?\n\n"
            "2. **output_clarity** (0-1): Are responses clear, well-structured, and easy to "
            "understand?\n"
            "   - Is the language clear and professional?\n"
            "   - Are complex topics explained well?\n"
            "   - Is formatting appropriate?\n\n"
            "3. **conversation_flow** (0-1): Does the conversation flow naturally?\n"
            "   - Are transitions between topics smooth?\n"
            "   - Does the assistant ask appropriate follow-up questions?\n"
            "   - Is the pacing appropriate?\n\n"
            "4. **detail_appropriateness** (0-1): Is the level of detail appropriate?\n"
            "   - Not too verbose or too brief?\n"
            "   - Important details included, unnecessary details omitted?\n\n"
            "Evaluate each criterion and provide specific examples from the conversation to "
            "support your scores.\n"
        )

    def parse_evaluation_response(self, response: str) -> List[EvaluationResult]:
        return self._parse_standard_response(response)
