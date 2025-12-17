"""
Base evaluator class for LLM-based conversation evaluation.

Provides shared infrastructure for all specialized evaluators including:
- Score normalization (0-1 scale)
- PASS/FAIL determination
- Structured feedback generation
- Deterministic evaluation (temperature=0)
"""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional

from openai import AsyncOpenAI

from tests.e2e.conversation_executor import ConversationResult

# Import E2E model constant
try:
    from tests.e2e.conftest import E2E_MODEL
except ImportError:
    E2E_MODEL = "gpt-4o-mini"  # Fallback if running standalone

if TYPE_CHECKING:
    from tests.e2e.trace_summarizer import TraceSummary


class EvaluationCriteria(str, Enum):
    """Standard evaluation criteria for conversations."""

    # Conversation-level criteria
    GOAL_COMPLETION = "goal_completion"
    CONSTRAINT_ADHERENCE = "constraint_adherence"
    GROUNDEDNESS = "groundedness"
    AMBIGUITY_HANDLING = "ambiguity_handling"
    OUTPUT_CLARITY = "output_clarity"
    SAFETY_COMPLIANCE = "safety_compliance"

    # Node-level criteria
    ROUTING_ACCURACY = "routing_accuracy"
    STATE_TRANSITION_VALIDITY = "state_transition_validity"
    TOOL_SCHEMA_CORRECTNESS = "tool_schema_correctness"
    ERROR_HANDLING = "error_handling"


@dataclass
class EvaluationResult:
    """Result of a single evaluation criterion."""

    criterion: str
    score: float  # 0.0 to 1.0
    passed: bool
    feedback: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "criterion": self.criterion,
            "score": self.score,
            "passed": self.passed,
            "feedback": self.feedback,
            "details": self.details,
        }


@dataclass
class EvaluationReport:
    """Complete evaluation report for a conversation."""

    scenario_id: str
    evaluator_name: str
    results: List[EvaluationResult] = field(default_factory=list)
    overall_score: float = 0.0
    overall_passed: bool = True
    summary: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "evaluator_name": self.evaluator_name,
            "results": [r.to_dict() for r in self.results],
            "overall_score": self.overall_score,
            "overall_passed": self.overall_passed,
            "summary": self.summary,
            "metadata": self.metadata,
        }

    def add_result(self, result: EvaluationResult) -> None:
        """Add a result and update overall metrics."""
        self.results.append(result)
        self._update_overall()

    def _update_overall(self) -> None:
        """Recalculate overall score and pass status."""
        if not self.results:
            return

        self.overall_score = sum(r.score for r in self.results) / len(self.results)
        self.overall_passed = all(r.passed for r in self.results)


class BaseEvaluator(ABC):
    """
    Abstract base class for LLM-based evaluators.

    All evaluators use temperature=0 for deterministic, reproducible evaluation.
    Uses GPT-4o exclusively for evaluation consistency.
    """

    # Subclasses should override these
    name: str = "base_evaluator"
    description: str = "Base evaluator"
    criteria: List[EvaluationCriteria] = []
    pass_threshold: float = 0.7

    def __init__(
        self,
        model: str = E2E_MODEL,
        api_key: Optional[str] = None,
        pass_threshold: Optional[float] = None,
    ):
        self.model = model
        self._api_key = api_key or os.getenv("OPENAI_API_KEY")
        self._client: Optional[AsyncOpenAI] = None
        if pass_threshold is not None:
            self.pass_threshold = pass_threshold

    @property
    def client(self) -> AsyncOpenAI:
        if self._client is None:
            self._client = AsyncOpenAI(api_key=self._api_key)
        return self._client

    @abstractmethod
    def get_evaluation_prompt(
        self,
        summary: TraceSummary,
        scenario_goal: str,
        scenario_constraints: Dict[str, Any],
    ) -> str:
        """Generate the evaluation prompt for this evaluator."""
        pass

    @abstractmethod
    def parse_evaluation_response(
        self,
        response: str,
    ) -> List[EvaluationResult]:
        """Parse the LLM response into evaluation results."""
        pass

    async def evaluate(
        self,
        result: ConversationResult,
        scenario_goal: str = "",
        scenario_constraints: Optional[Dict[str, Any]] = None,
        trace_summary: Optional["TraceSummary"] = None,
    ) -> EvaluationReport:
        """
        Evaluate a conversation result.

        Args:
            result: The conversation result to evaluate
            scenario_goal: The intended goal of the conversation
            scenario_constraints: Constraints that should have been followed
            trace_summary: Optional pre-computed trace summary (with LangSmith data if available)

        Returns:
            EvaluationReport with scores and feedback
        """
        from tests.e2e.trace_summarizer import TraceSummarizer

        # Use provided summary or create one
        if trace_summary is not None:
            summary = trace_summary
        else:
            summarizer = TraceSummarizer()
            summary = summarizer.summarize_local(result)

        # Generate evaluation prompt
        prompt = self.get_evaluation_prompt(
            summary=summary,
            scenario_goal=scenario_goal,
            scenario_constraints=scenario_constraints or {},
        )

        # Call LLM with temperature=0 for determinism
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            temperature=0,  # Deterministic evaluation
            max_tokens=2048,
            response_format={"type": "json_object"},
        )

        content = response.choices[0].message.content
        if not content:
            raise ValueError("Empty response from evaluator LLM")

        # Parse response into results
        results = self.parse_evaluation_response(content)

        # Build report
        report = EvaluationReport(
            scenario_id=result.scenario_id,
            evaluator_name=self.name,
            metadata={
                "model": self.model,
                "pass_threshold": self.pass_threshold,
            },
        )

        for eval_result in results:
            report.add_result(eval_result)

        # Generate summary
        report.summary = self._generate_summary(report)

        return report

    def _get_system_prompt(self) -> str:
        """Get the system prompt for evaluation."""
        return f"""You are an expert evaluator for a travel planning AI assistant.

Your role is to evaluate conversation traces using the {self.name} criteria.

{self.description}

EVALUATION RULES:
1. Score each criterion on a 0.0 to 1.0 scale
2. 0.0 = Complete failure
3. 0.5 = Partial success with significant issues
4. 1.0 = Perfect execution
5. A score >= {self.pass_threshold} is considered PASS, below is FAIL
6. Provide specific, actionable feedback for each criterion
7. Be objective and consistent

RESPONSE FORMAT:
Return a JSON object with this structure:
{{
    "evaluations": [
        {{
            "criterion": "criterion_name",
            "score": 0.0-1.0,
            "passed": true/false,
            "feedback": "Specific feedback",
            "details": {{}}
        }}
    ],
    "overall_assessment": "Brief overall assessment"
}}
"""

    def _generate_summary(self, report: EvaluationReport) -> str:
        """Generate a human-readable summary of the evaluation."""
        passed_count = sum(1 for r in report.results if r.passed)
        total = len(report.results)

        status = "PASSED" if report.overall_passed else "FAILED"

        return (
            f"{self.name} evaluation {status}: "
            f"{passed_count}/{total} criteria passed, "
            f"overall score {report.overall_score:.2f}"
        )

    def _parse_standard_response(self, content: str) -> List[EvaluationResult]:
        """Parse a standard JSON evaluation response."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            return [
                EvaluationResult(
                    criterion="parse_error",
                    score=0.0,
                    passed=False,
                    feedback=f"Failed to parse evaluation response: {content[:200]}",
                )
            ]

        results = []
        for eval_data in data.get("evaluations", []):
            score = float(eval_data.get("score", 0))
            results.append(
                EvaluationResult(
                    criterion=eval_data.get("criterion", "unknown"),
                    score=score,
                    passed=eval_data.get("passed", score >= self.pass_threshold),
                    feedback=eval_data.get("feedback", ""),
                    details=eval_data.get("details", {}),
                )
            )

        return results


class CompositeEvaluator:
    """Runs multiple evaluators and aggregates results."""

    def __init__(self, evaluators: List[BaseEvaluator]):
        self.evaluators = evaluators

    async def evaluate(
        self,
        result: ConversationResult,
        scenario_goal: str = "",
        scenario_constraints: Optional[Dict[str, Any]] = None,
        trace_summary: Optional["TraceSummary"] = None,
    ) -> Dict[str, EvaluationReport]:
        """
        Run all evaluators and return combined results.

        Args:
            result: The conversation result to evaluate
            scenario_goal: The intended goal of the conversation
            scenario_constraints: Constraints that should have been followed
            trace_summary: Optional pre-computed trace summary (with LangSmith data if available)

        Returns:
            Dict mapping evaluator names to EvaluationReport objects
        """
        reports = {}

        for evaluator in self.evaluators:
            report = await evaluator.evaluate(
                result=result,
                scenario_goal=scenario_goal,
                scenario_constraints=scenario_constraints,
                trace_summary=trace_summary,
            )
            reports[evaluator.name] = report

        return reports

    def get_aggregate_score(self, reports: Dict[str, EvaluationReport]) -> float:
        """Calculate weighted average score across all evaluators."""
        if not reports:
            return 0.0

        total_score = sum(r.overall_score for r in reports.values())
        return total_score / len(reports)

    def get_all_failures(
        self,
        reports: Dict[str, EvaluationReport],
    ) -> List[Dict[str, Any]]:
        """Get all failing criteria across evaluators."""
        failures = []

        for name, report in reports.items():
            for result in report.results:
                if not result.passed:
                    failures.append(
                        {
                            "evaluator": name,
                            "criterion": result.criterion,
                            "score": result.score,
                            "feedback": result.feedback,
                        }
                    )

        return failures
