"""
End-to-end LLM-driven conversation testing framework.

This module provides infrastructure for:
- Generating synthetic conversation scenarios using LLMs
- Replaying conversations through LangGraph
- Capturing traces via LangSmith
- Evaluating conversation quality using LLM-based judges

Usage:
    from tests.e2e import ScenarioGenerator, ConversationExecutor
    from tests.e2e.evaluators import QualityEvaluator, SafetyEvaluator

    # Generate scenarios
    generator = ScenarioGenerator()
    scenarios = await generator.generate_scenario_batch(count=5)

    # Execute conversations
    executor = ConversationExecutor(enable_langsmith=True)
    for scenario in scenarios:
        result = await executor.execute_scenario(scenario)

    # Evaluate results
    evaluator = QualityEvaluator()
    report = await evaluator.evaluate(result, scenario_goal=scenario.goal)
"""


# Lazy imports to avoid circular dependencies
def __getattr__(name):
    if name == "ScenarioGenerator":
        from tests.e2e.scenario_generator import ScenarioGenerator

        return ScenarioGenerator
    elif name == "ConversationScenario":
        from tests.e2e.scenario_generator import ConversationScenario

        return ConversationScenario
    elif name == "ConversationExecutor":
        from tests.e2e.conversation_executor import ConversationExecutor

        return ConversationExecutor
    elif name == "ConversationResult":
        from tests.e2e.conversation_executor import ConversationResult

        return ConversationResult
    elif name == "TraceSummarizer":
        from tests.e2e.trace_summarizer import TraceSummarizer

        return TraceSummarizer
    elif name == "TraceSummary":
        from tests.e2e.trace_summarizer import TraceSummary

        return TraceSummary
    elif name == "DatasetLogger":
        from tests.e2e.dataset_logger import DatasetLogger

        return DatasetLogger
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ScenarioGenerator",
    "ConversationScenario",
    "ConversationExecutor",
    "ConversationResult",
    "TraceSummarizer",
    "TraceSummary",
    "DatasetLogger",
]
