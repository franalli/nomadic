"""
Constraint evaluator for checking adherence to dates, budget, and preferences.
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


class ConstraintEvaluator(BaseEvaluator):
    """Evaluates adherence to user-specified constraints."""

    name = "constraint_evaluator"
    description = """Evaluates:
- Correct extraction and application of dates
- Budget constraints respected
- User preferences honored
- Special requirements accommodated
- Party size and composition handled correctly"""

    criteria = [EvaluationCriteria.CONSTRAINT_ADHERENCE]
    pass_threshold = get_threshold("constraint")

    def get_evaluation_prompt(
        self,
        summary: TraceSummary,
        scenario_goal: str,
        scenario_constraints: Dict[str, Any],
    ) -> str:
        transcript = summary.get_transcript_text()

        # Format constraints for the prompt
        constraints_text = ""
        if scenario_constraints:
            if scenario_constraints.get("budget"):
                constraints_text += f"- Budget: {scenario_constraints['budget']}\n"
            if scenario_constraints.get("dates"):
                constraints_text += f"- Dates: {scenario_constraints['dates']}\n"
            if scenario_constraints.get("preferences"):
                constraints_text += (
                    f"- Preferences: {', '.join(scenario_constraints['preferences'])}\n"
                )
            if scenario_constraints.get("avoid"):
                constraints_text += f"- Avoid: {', '.join(scenario_constraints['avoid'])}\n"
            if scenario_constraints.get("party_size"):
                constraints_text += f"- Party Size: {scenario_constraints['party_size']}\n"
            if scenario_constraints.get("special_requirements"):
                constraints_text += (
                    "- Special Requirements: "
                    f"{', '.join(scenario_constraints['special_requirements'])}\n"
                )

        budget_value = summary.final_trip_inputs.get("budget", "Not specified")
        currency_value = summary.final_trip_inputs.get("currency", "")

        return f"""Evaluate how well the travel assistant adhered to the user's constraints.

## User's Specified Constraints
{constraints_text or "No explicit constraints provided in scenario"}

## Conversation Transcript
{transcript}

## Extracted Information
- Destinations: {summary.final_trip_inputs.get('destinations', [])}
- Origin: {summary.final_trip_inputs.get('origin', 'Not specified')}
- Start Date: {summary.final_trip_inputs.get('start_date', 'Not specified')}
- End Date: {summary.final_trip_inputs.get('end_date', 'Not specified')}
- Adults: {summary.final_trip_inputs.get('adults', 'Not specified')}
- Children: {summary.final_trip_inputs.get('children', 'Not specified')}
- Budget: {budget_value} {currency_value}

## Evaluation Criteria

1. **date_extraction** (0-1): Were dates correctly understood and extracted?
   - Did the system understand relative dates ("next month", "in March")?
   - Are date formats correct (ISO format)?
   - Were date ranges handled properly?

2. **budget_adherence** (0-1): Was the budget constraint respected?
   - Was the budget value extracted correctly?
   - Were recommendations within budget?
   - Was currency handled correctly?

3. **preference_handling** (0-1): Were user preferences incorporated?
   - Were positive preferences (likes) acknowledged?
   - Were negative preferences (dislikes/avoid) respected?
   - Did suggestions align with stated preferences?

4. **party_composition** (0-1): Was party size/composition handled correctly?
   - Number of adults/children extracted correctly?
   - Appropriate accommodations for the group?
   - Special needs (accessibility, dietary) addressed?

For each criterion, compare what the user asked for against what was extracted/recommended.
"""

    def parse_evaluation_response(self, response: str) -> List[EvaluationResult]:
        return self._parse_standard_response(response)
