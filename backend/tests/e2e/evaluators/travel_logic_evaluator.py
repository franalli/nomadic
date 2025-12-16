"""
Travel logic evaluator for date math, budget calculations, and availability.
"""

from __future__ import annotations

from typing import Any, Dict, List

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
    pass_threshold = 0.8  # Date/budget errors cause real harm to travelers

    def get_evaluation_prompt(
        self,
        summary: TraceSummary,
        scenario_goal: str,
        scenario_constraints: Dict[str, Any],
    ) -> str:
        transcript = summary.get_transcript_text()

        # Extract relevant data
        trip = summary.final_trip_inputs

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
{len(summary.final_branches)} branches generated

## Evaluation Criteria

1. **date_logic** (0-1): Is date math correct?
   - Trip duration calculations accurate
   - Relative date parsing correct ("next month", "in 2 weeks")
   - No impossible date combinations (end before start)
   - Timezone considerations acknowledged when relevant

2. **budget_logic** (0-1): Is budget handling logical?
   - Budget allocations reasonable
   - Currency conversions handled correctly
   - Per-person vs total budget clear
   - Recommendations align with stated budget

3. **itinerary_feasibility** (0-1): Is the itinerary geographically feasible?
   - Travel times between destinations reasonable
   - Connection times for flights logical
   - Activity scheduling practical
   - No physically impossible combinations

4. **logistics_coherence** (0-1): Are logistical details coherent?
   - Check-in/check-out times sensible
   - Activity bookings at appropriate times
   - Transportation connections logical
   - Seasonal appropriateness considered

EXAMPLES OF FAILURES:
- Suggesting a day trip that requires 12+ hours of travel
- Booking departure before arrival
- Recommending skiing in July for northern hemisphere
- Budget of $500 for 2-week luxury trip
"""

    def parse_evaluation_response(self, response: str) -> List[EvaluationResult]:
        return self._parse_standard_response(response)
