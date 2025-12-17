"""
Travel logic evaluator for date math, budget calculations, and availability.
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


class TravelLogicEvaluator(BaseEvaluator):
    """Evaluates travel-specific logic like dates, budgets, and logistics."""

    name = "travel_logic_evaluator"
    description = """Evaluates:
- Date arithmetic and duration calculations
- Budget math and currency handling
- Logical itinerary sequencing
- Geographic feasibility
- Timing and availability logic"""

    criteria = [
        EvaluationCriteria.CONSTRAINT_ADHERENCE,
        EvaluationCriteria.GROUNDEDNESS,
    ]
    pass_threshold = get_threshold("travel_logic")

    def get_evaluation_prompt(
        self,
        summary: TraceSummary,
        scenario_goal: str,
        scenario_constraints: Dict[str, Any],
    ) -> str:
        transcript = summary.get_transcript_text()

        # Extract relevant data
        trip = summary.final_trip_inputs
        branches_count = len(summary.final_branches)

        # Determine if this is an early-stage/information-gathering conversation
        has_itinerary = branches_count > 0

        # Build stage-aware evaluation instructions
        if has_itinerary:
            itinerary_instructions = (
                "3. **itinerary_feasibility** (0-1): "
                "Is the itinerary geographically feasible?\n"
                "   - Travel times between destinations reasonable\n"
                "   - Connection times for flights logical\n"
                "   - Activity scheduling practical\n"
                "   - No physically impossible combinations\n\n"
                "4. **logistics_coherence** (0-1): Are logistical details coherent?\n"
                "   - Check-in/check-out times sensible\n"
                "   - Activity bookings at appropriate times\n"
                "   - Transportation connections logical\n"
                "   - Seasonal appropriateness considered"
            )
        else:
            itinerary_instructions = (
                "3. **itinerary_feasibility**: N/A - No itinerary generated yet\n"
                "   - Score as N/A (exclude from average) since conversation is in\n"
                "     information-gathering phase\n"
                "   - Do NOT penalize early-stage conversations for not having a "
                "complete itinerary\n\n"
                "4. **logistics_coherence**: N/A - No itinerary generated yet\n"
                "   - Score as N/A (exclude from average) since conversation is in\n"
                "     information-gathering phase\n"
                "   - Do NOT penalize early-stage conversations for not having "
                "logistics details"
            )

        stage_note = (
            "**Note: This is an early-stage/information-gathering conversation without a "
            "complete itinerary.**"
            if not has_itinerary
            else ""
        )

        return f"""Evaluate the travel-specific logic in this planning conversation.

## Conversation Transcript
{transcript}

## Extracted Trip Details
- Destinations: {trip.get('destinations', [])}
- Origin: {trip.get('origin', 'Not specified')}
- Start Date: {trip.get('start_date', 'Not specified')}
- End Date: {trip.get('end_date', 'Not specified')}
- Budget: {trip.get('budget', 'Not specified')} {trip.get('currency', 'USD')}
- Adults: {trip.get('adults', 'Not specified')}
- Children: {trip.get('children', 'Not specified')}

## Branches/Itinerary Generated
{branches_count} branches generated
{stage_note}

## Evaluation Criteria

1. **date_logic** (0-1): Is date math correct?
   - Trip duration calculations accurate
   - Relative date parsing correct ("next month", "in 2 weeks")
   - No impossible date combinations (end before start)
   - Timezone considerations acknowledged when relevant
   - If no dates discussed yet, score 1.0 (no errors to detect)

2. **budget_logic** (0-1): Is budget handling logical?
   - Budget allocations reasonable
   - Currency conversions handled correctly
   - Per-person vs total budget clear
   - Recommendations align with stated budget
   - If no budget discussed yet, score 1.0 (no errors to detect)

{itinerary_instructions}

## IMPORTANT SCORING RULES:
- For N/A criteria (when no itinerary exists), output the criterion name but DO NOT include a score
- Only calculate the average from criteria that have numeric scores
- Early-stage conversations should be evaluated ONLY on date_logic and budget_logic
- Do NOT penalize for missing information that hasn't been discussed yet

EXAMPLES OF FAILURES:
- Suggesting a day trip that requires 12+ hours of travel
- Booking departure before arrival
- Recommending skiing in July for northern hemisphere
- Budget of $500 for 2-week luxury trip

## RESPONSE FORMAT:
For each criterion, provide:
- **criterion_name**: score (0-1) OR "N/A"
- Reasoning: brief explanation

Then provide:
- **average_score**: (calculated ONLY from numeric scores, excluding N/A)
"""

    def parse_evaluation_response(self, response: str) -> List[EvaluationResult]:
        return self._parse_standard_response(response)
