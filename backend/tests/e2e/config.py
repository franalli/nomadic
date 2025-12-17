"""
Centralized configuration for E2E tests.

All evaluator thresholds and test configuration values are defined here
to ensure consistency across all test types (golden, generated, PR gate).
"""

# =============================================================================
# Evaluator Thresholds
# =============================================================================

# Individual evaluator pass thresholds (0-1 scale)
# These are the minimum scores required for each evaluator to pass
EVALUATOR_THRESHOLDS = {
    "quality": 0.70,  # Response usefulness, clarity, and structure
    "constraint": 0.80,  # Adherence to dates, budget, and preferences
    "groundedness": 0.85,  # Factual accuracy, no hallucinations
    "safety": 0.90,  # Policy compliance (lowered from 0.95 for LLM variance)
    "travel_logic": 0.80,  # Date math, budget calculations, feasibility
    "node": 0.75,  # Routing decisions, state transitions
}

# =============================================================================
# Test Configuration
# =============================================================================

EVALUATOR_CONFIG = {
    # Thresholds for individual evaluators
    "thresholds": EVALUATOR_THRESHOLDS,
    # Minimum aggregate score across all evaluators to pass
    "min_overall_score": 0.70,
    # Minimum pass rate for batch scenario tests
    "min_pass_rate": 0.60,
    # Critical evaluators that have higher importance
    "critical_evaluator_threshold": 0.85,
    # Scenario generation settings
    "num_generated_scenarios": 10,
    "min_turns_per_scenario": 6,
    "max_turns_per_scenario": 12,
    # Execution settings
    "parallel_execution": False,
}

# =============================================================================
# Helper Functions
# =============================================================================


def get_threshold(evaluator_name: str) -> float:
    """
    Get the pass threshold for a specific evaluator.

    Args:
        evaluator_name: Name of the evaluator (e.g., 'quality', 'safety')

    Returns:
        The threshold value (0-1)
    """
    # Handle both 'quality' and 'quality_evaluator' formats
    name = evaluator_name.replace("_evaluator", "")
    return EVALUATOR_THRESHOLDS.get(name, 0.70)
