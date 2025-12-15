"""
Dataset logger for storing evaluation results in LangSmith.

Persists evaluated conversation runs as LangSmith dataset examples
with evaluator outputs as structured metadata for regression tracking.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from tests.e2e.conversation_executor import ConversationResult
from tests.e2e.evaluators.base_evaluator import EvaluationReport
from tests.e2e.trace_summarizer import TraceSummary


@dataclass
class DatasetExample:
    """A single example in a LangSmith dataset."""

    example_id: str
    scenario_id: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
    evaluation_results: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.example_id,
            "scenario_id": self.scenario_id,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "metadata": self.metadata,
            "evaluation_results": self.evaluation_results,
        }


class DatasetLogger:
    """
    Logs evaluation results to LangSmith datasets.

    Each evaluated conversation becomes a dataset example with:
    - Inputs: scenario definition, user messages
    - Outputs: assistant messages, final state
    - Metadata: evaluation scores, pass/fail status, feedback
    """

    def __init__(
        self,
        dataset_name: str = "nomadic_e2e_evaluations",
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
        project_name: str = "nomadic-evaluations",
    ):
        self.dataset_name = dataset_name
        self.project_name = project_name
        self._api_key = api_key or os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
        self._api_url = (
            api_url or os.getenv("LANGSMITH_ENDPOINT") or os.getenv("LANGCHAIN_ENDPOINT")
        )
        self._client = None
        self._dataset = None

    @property
    def client(self):
        """Lazy-load LangSmith client."""
        if self._client is None:
            try:
                from langsmith import Client

                self._client = Client(api_key=self._api_key, api_url=self._api_url)
            except ImportError as err:
                raise ImportError("langsmith package required for dataset logging") from err
        return self._client

    def _get_or_create_dataset(self):
        """Get existing dataset or create a new one."""
        if self._dataset is not None:
            return self._dataset

        # Try to get existing dataset
        try:
            datasets = list(self.client.list_datasets(dataset_name=self.dataset_name))
            if datasets:
                self._dataset = datasets[0]
                return self._dataset
        except Exception:
            pass

        # Create new dataset
        self._dataset = self.client.create_dataset(
            dataset_name=self.dataset_name,
            description="E2E conversation evaluation results for the Nomadic travel planner",
        )
        return self._dataset

    def log_evaluation(
        self,
        result: ConversationResult,
        summary: TraceSummary,
        evaluation_reports: Dict[str, EvaluationReport],
        scenario_goal: str = "",
        scenario_constraints: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Log an evaluated conversation to the LangSmith dataset.

        Args:
            result: The conversation execution result
            summary: Normalized trace summary
            evaluation_reports: Reports from all evaluators
            scenario_goal: The intended goal
            scenario_constraints: The constraints

        Returns:
            The example ID in the dataset
        """
        dataset = self._get_or_create_dataset()

        # Build inputs
        inputs = {
            "scenario_id": result.scenario_id,
            "scenario_goal": scenario_goal,
            "scenario_constraints": scenario_constraints or {},
            "user_messages": [
                {"turn": t.turn_number, "message": t.user_message} for t in result.turns
            ],
        }

        # Build outputs
        outputs = {
            "assistant_messages": [
                {"turn": t.turn_number, "message": t.assistant_message} for t in result.turns
            ],
            "final_trip_inputs": summary.final_trip_inputs,
            "final_branches": summary.final_branches,
            "intent_sequence": result.intent_sequence,
        }

        # Build evaluation metadata
        eval_metadata = {}
        all_passed = True
        total_score = 0.0
        num_evaluators = 0

        for name, report in evaluation_reports.items():
            eval_metadata[name] = {
                "overall_score": report.overall_score,
                "overall_passed": report.overall_passed,
                "summary": report.summary,
                "results": [r.to_dict() for r in report.results],
            }
            if not report.overall_passed:
                all_passed = False
            total_score += report.overall_score
            num_evaluators += 1

        avg_score = total_score / num_evaluators if num_evaluators > 0 else 0.0

        # Build full metadata
        metadata = {
            "thread_id": result.thread_id,
            "total_turns": len(result.turns),
            "total_llm_calls": result.total_llm_calls,
            "total_duration_ms": result.total_duration_ms,
            "model_versions": result.model_versions,
            "config_flags": result.config_flags,
            "started_at": result.started_at,
            "completed_at": result.completed_at,
            "errors_encountered": result.errors_encountered,
            # LangSmith trace IDs for trace-to-evaluation correlation
            "langsmith_run_ids": result.run_ids,
            "evaluation": {
                "all_passed": all_passed,
                "average_score": avg_score,
                "evaluator_count": num_evaluators,
                "evaluators": eval_metadata,
            },
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }

        # Create example in dataset
        example = self.client.create_example(
            dataset_id=dataset.id,
            inputs=inputs,
            outputs=outputs,
            metadata=metadata,
        )

        return str(example.id)

    def log_failure(
        self,
        result: ConversationResult,
        evaluation_reports: Dict[str, EvaluationReport],
        failure_reason: str,
    ) -> str:
        """
        Log a failed evaluation for regression tracking.

        Failed evaluations are stored separately for analysis and debugging.
        """
        from tests.e2e.trace_summarizer import TraceSummarizer

        summarizer = TraceSummarizer()
        summary = summarizer.summarize_local(result)

        # Get failures across evaluators
        failures = []
        for name, report in evaluation_reports.items():
            for eval_result in report.results:
                if not eval_result.passed:
                    failures.append(
                        {
                            "evaluator": name,
                            "criterion": eval_result.criterion,
                            "score": eval_result.score,
                            "feedback": eval_result.feedback,
                        }
                    )

        return self.log_evaluation(
            result=result,
            summary=summary,
            evaluation_reports=evaluation_reports,
            scenario_goal=failure_reason,
            scenario_constraints={"failures": failures},
        )

    def get_recent_results(
        self,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Get recent evaluation results from the dataset."""
        dataset = self._get_or_create_dataset()

        examples = list(
            self.client.list_examples(
                dataset_id=dataset.id,
                limit=limit,
            )
        )

        return [
            {
                "id": str(ex.id),
                "scenario_id": ex.inputs.get("scenario_id"),
                "passed": ex.metadata.get("evaluation", {}).get("all_passed", False),
                "score": ex.metadata.get("evaluation", {}).get("average_score", 0),
                "logged_at": ex.metadata.get("logged_at"),
            }
            for ex in examples
        ]

    def get_failure_rate(
        self,
        last_n: int = 100,
    ) -> Dict[str, float]:
        """Calculate failure rates per evaluator over recent runs."""
        dataset = self._get_or_create_dataset()

        examples = list(
            self.client.list_examples(
                dataset_id=dataset.id,
                limit=last_n,
            )
        )

        if not examples:
            return {}

        evaluator_stats: Dict[str, Dict[str, int]] = {}

        for ex in examples:
            eval_data = ex.metadata.get("evaluation", {}).get("evaluators", {})
            for name, data in eval_data.items():
                if name not in evaluator_stats:
                    evaluator_stats[name] = {"passed": 0, "failed": 0}

                if data.get("overall_passed", False):
                    evaluator_stats[name]["passed"] += 1
                else:
                    evaluator_stats[name]["failed"] += 1

        # Calculate rates
        failure_rates = {}
        for name, stats in evaluator_stats.items():
            total = stats["passed"] + stats["failed"]
            failure_rates[name] = stats["failed"] / total if total > 0 else 0.0

        return failure_rates

    def get_score_trend(
        self,
        evaluator_name: str,
        last_n: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get score trend for a specific evaluator."""
        dataset = self._get_or_create_dataset()

        examples = list(
            self.client.list_examples(
                dataset_id=dataset.id,
                limit=last_n,
            )
        )

        trend = []
        for ex in examples:
            eval_data = ex.metadata.get("evaluation", {}).get("evaluators", {})
            if evaluator_name in eval_data:
                trend.append(
                    {
                        "id": str(ex.id),
                        "score": eval_data[evaluator_name].get("overall_score", 0),
                        "passed": eval_data[evaluator_name].get("overall_passed", False),
                        "logged_at": ex.metadata.get("logged_at"),
                    }
                )

        return trend


class LocalDatasetLogger:
    """
    Local file-based dataset logger for testing without LangSmith.

    Saves evaluation results to JSON files for local analysis.
    """

    def __init__(self, output_dir: str = "e2e_results"):
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def log_evaluation(
        self,
        result: ConversationResult,
        summary: TraceSummary,
        evaluation_reports: Dict[str, EvaluationReport],
        scenario_goal: str = "",
        scenario_constraints: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Log evaluation to a local JSON file."""
        filename = f"{result.scenario_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        filepath = os.path.join(self.output_dir, filename)

        data = {
            "scenario_id": result.scenario_id,
            "thread_id": result.thread_id,
            "scenario_goal": scenario_goal,
            "scenario_constraints": scenario_constraints,
            "conversation": result.to_dict(),
            "summary": summary.to_dict(),
            "evaluations": {name: report.to_dict() for name, report in evaluation_reports.items()},
            "logged_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

        return filepath
