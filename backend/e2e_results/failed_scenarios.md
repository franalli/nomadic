# E2E Test Diagnostic Report

**Session:** 20251216-001621
**Timestamp:** 2025-12-16T00:16:21.942867
**Project:** nomadic-e2e-tests

## Summary

- **Total Tests:** 2
- **Passed:** 1
- **Failed:** 1
- **Pass Rate:** 50.0%
- **Duration:** 26.00s

## Evaluator Breakdown

| Evaluator | Passed | Failed |
|-----------|--------|--------|
| constraint_evaluator | 0 | 1 |
| node_evaluator | 0 | 1 |
| quality_evaluator | 0 | 1 |
| safety_evaluator | 2 | 0 |

## Failures by Category

### Constraint Violation (4)

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** constraint_evaluator
- **Criterion:** date_extraction
- **Score:** 0.00
- **Feedback:** The system failed to extract the specified dates (March 15-20, 2025) from the conversation.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** constraint_evaluator
- **Criterion:** budget_adherence
- **Score:** 0.00
- **Feedback:** The system did not extract the budget of $5000, so it could not ensure recommendations were within budget.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** constraint_evaluator
- **Criterion:** preference_handling
- **Score:** 0.50
- **Feedback:** The system acknowledged the user's interest in romantic restaurants, museums, and wine tours, but there is no evidence of specific recommendations being made.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** constraint_evaluator
- **Criterion:** party_composition
- **Score:** 0.00
- **Feedback:** The system did not extract the party size of 2 adults, which is crucial for making appropriate travel arrangements.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

### Quality Issue (4)

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** quality_evaluator
- **Criterion:** response_usefulness
- **Score:** 0.00
- **Feedback:** The assistant did not provide any responses or suggestions to the user's queries. There was no information on romantic restaurants, flights, or hotels, which are crucial for planning the trip.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** quality_evaluator
- **Criterion:** output_clarity
- **Score:** 0.00
- **Feedback:** There were no responses from the assistant, so clarity cannot be assessed. The conversation lacks any structured output or guidance.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** quality_evaluator
- **Criterion:** conversation_flow
- **Score:** 0.00
- **Feedback:** The conversation does not flow as there are no responses from the assistant. The user provided detailed information, but the assistant did not engage or continue the conversation.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** quality_evaluator
- **Criterion:** detail_appropriateness
- **Score:** 0.00
- **Feedback:** The assistant did not provide any details, making it impossible to evaluate the appropriateness of detail. The user's requests for specific information were not addressed.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

### Routing Error (1)

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** node_evaluator
- **Criterion:** routing_accuracy
- **Score:** 0.00
- **Feedback:** No routing decisions were recorded, indicating a complete failure in identifying user intent and invoking appropriate specialist nodes.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

### Unknown (3)

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** node_evaluator
- **Criterion:** state_transitions
- **Score:** 0.00
- **Feedback:** No state transitions were recorded, suggesting that the system failed to track or evolve the trip inputs across turns.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** node_evaluator
- **Criterion:** error_handling
- **Score:** 0.00
- **Feedback:** Errors were not handled appropriately. The repeated 'object.__init__()' error indicates a systemic issue that was not addressed, and no error messages were provided to the user.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...

#### golden_simple_paris_trip

- **Test:** test_golden_scenario_quality
- **Evaluator:** node_evaluator
- **Criterion:** efficiency
- **Score:** 0.00
- **Feedback:** The system was not efficient as there were no LLM calls or caching, and the total duration was 0ms, indicating no processing occurred.
- **Turn:** 6
- **User Message:** And a nice boutique hotel in the Marais district?...
