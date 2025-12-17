"""
Conversation executor for replaying scenarios through LangGraph.

Feeds user messages sequentially into run_turn(), preserving state
across turns, and captures full conversation traces for evaluation.
"""

from __future__ import annotations

import asyncio
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional
from uuid import uuid4

# Add backend to path for imports
BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

if TYPE_CHECKING:
    from tests.e2e.scenario_generator import ConversationScenario


@dataclass
class TurnResult:
    """Result of a single conversation turn."""

    turn_number: int
    user_message: str
    assistant_message: str
    trip_inputs: Dict[str, Any]
    ready_to_generate: bool
    branches: List[Dict[str, Any]]
    suggested_responses: List[str]
    errors: List[str]
    session_state: Dict[str, Any]

    # LangSmith trace ID for this turn
    run_id: Optional[str] = None

    # Observability metrics
    router_intent: Optional[str] = None
    strategy_topic: Optional[str] = None
    short_circuit_type: Optional[str] = None
    llm_calls_made: int = 0
    cache_hits: int = 0
    confidence_routing: Optional[str] = None

    # Token and timing metrics
    total_tokens: int = 0
    node_tokens: Dict[str, int] = field(default_factory=dict)
    llm_time_ms: float = 0.0

    # Timing
    duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_number": self.turn_number,
            "user_message": self.user_message,
            "assistant_message": self.assistant_message,
            "trip_inputs": self.trip_inputs,
            "ready_to_generate": self.ready_to_generate,
            "branches": self.branches,
            "suggested_responses": self.suggested_responses,
            "errors": self.errors,
            "run_id": self.run_id,
            "router_intent": self.router_intent,
            "strategy_topic": self.strategy_topic,
            "short_circuit_type": self.short_circuit_type,
            "llm_calls_made": self.llm_calls_made,
            "cache_hits": self.cache_hits,
            "confidence_routing": self.confidence_routing,
            "total_tokens": self.total_tokens,
            "node_tokens": self.node_tokens,
            "llm_time_ms": self.llm_time_ms,
            "duration_ms": self.duration_ms,
        }


@dataclass
class ConversationResult:
    """Complete result of executing a conversation scenario."""

    scenario_id: str
    thread_id: str
    turns: List[TurnResult] = field(default_factory=list)
    final_state: Dict[str, Any] = field(default_factory=dict)
    total_duration_ms: float = 0.0
    total_llm_calls: int = 0
    total_cache_hits: int = 0
    total_tokens: int = 0
    total_llm_time_ms: float = 0.0
    errors_encountered: List[str] = field(default_factory=list)

    # LangSmith trace IDs for each turn (for trace correlation)
    run_ids: List[str] = field(default_factory=list)

    # Execution metadata
    started_at: str = ""
    completed_at: str = ""
    model_versions: Dict[str, str] = field(default_factory=dict)
    config_flags: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        """Check if conversation completed without critical errors."""
        return len(self.errors_encountered) == 0

    @property
    def final_trip_inputs(self) -> Dict[str, Any]:
        """Get the final trip inputs after all turns."""
        if self.turns:
            return self.turns[-1].trip_inputs
        return {}

    @property
    def final_assistant_message(self) -> str:
        """Get the last assistant message."""
        if self.turns:
            return self.turns[-1].assistant_message
        return ""

    @property
    def intent_sequence(self) -> List[Optional[str]]:
        """Get the sequence of intents detected across turns."""
        return [t.router_intent for t in self.turns]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "thread_id": self.thread_id,
            "turns": [t.to_dict() for t in self.turns],
            "final_state": self.final_state,
            "total_duration_ms": self.total_duration_ms,
            "total_llm_calls": self.total_llm_calls,
            "total_cache_hits": self.total_cache_hits,
            "total_tokens": self.total_tokens,
            "total_llm_time_ms": self.total_llm_time_ms,
            "errors_encountered": self.errors_encountered,
            "run_ids": self.run_ids,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "model_versions": self.model_versions,
            "config_flags": self.config_flags,
            "success": self.success,
            "intent_sequence": self.intent_sequence,
        }


class ConversationExecutor:
    """Executes conversation scenarios through LangGraph."""

    def __init__(
        self,
        enable_langsmith: bool = True,
        langsmith_project: Optional[str] = None,
        capture_config_flags: bool = True,
    ):
        self.enable_langsmith = enable_langsmith
        self.langsmith_project = langsmith_project
        self.capture_config_flags = capture_config_flags
        self._run_turn = None  # Lazy import

    def _get_run_turn(self):
        """Lazy import of run_turn to avoid circular imports."""
        if self._run_turn is None:
            from app.plan_graph import run_turn

            self._run_turn = run_turn
        return self._run_turn

    def _setup_langsmith(self, scenario_id: str) -> None:
        """Configure LangSmith tracing for this execution."""
        if not self.enable_langsmith:
            return

        from app.config import configure_langsmith_tracing

        project = self.langsmith_project or "nomadic-evaluations"
        configure_langsmith_tracing(enabled=True, project=project)

        # Set run name for easy identification
        os.environ["LANGCHAIN_RUN_NAME"] = f"e2e_{scenario_id}"

    def _capture_config_flags(self) -> Dict[str, Any]:
        """Capture current configuration flags for reproducibility."""
        if not self.capture_config_flags:
            return {}

        from app.config import settings

        return {
            "enable_graph_plan_route": settings.enable_graph_plan_route,
            "enable_response_polish": settings.enable_response_polish,
            "enable_strategy_boating": settings.enable_strategy_boating,
            "enable_strategy_hiking": settings.enable_strategy_hiking,
            "enable_strategy_diving": settings.enable_strategy_diving,
            "enable_strategy_skiing": settings.enable_strategy_skiing,
            "enable_strategy_cycling": settings.enable_strategy_cycling,
            "llm_timeout_router": settings.llm_timeout_router,
            "llm_timeout_specialist": settings.llm_timeout_specialist,
            "openai_plan_temperature": settings.openai_plan_temperature,
        }

    def _get_model_versions(self) -> Dict[str, str]:
        """Get current model versions for logging."""
        return {
            "small": os.getenv("OPENAI_SMALL_MODEL", "gpt-4o-mini"),
            "medium": os.getenv("OPENAI_MEDIUM_MODEL", "gpt-4o-mini"),
            "large": os.getenv("OPENAI_PLAN_MODEL", "gpt-4o-mini"),
        }

    async def execute_scenario(
        self,
        scenario: ConversationScenario,
        initial_trip_inputs: Optional[Dict[str, Any]] = None,
        metadata_tags: Optional[Dict[str, Any]] = None,
    ) -> ConversationResult:
        """
        Execute a complete conversation scenario.

        Args:
            scenario: The conversation scenario to execute
            initial_trip_inputs: Optional initial trip inputs to seed the conversation
            metadata_tags: Additional metadata to attach to the trace

        Returns:
            ConversationResult with all turn results and final state
        """
        run_turn = self._get_run_turn()

        thread_id = str(uuid4())
        started_at = datetime.now(timezone.utc).isoformat()

        # Setup LangSmith tracing
        self._setup_langsmith(scenario.scenario_id)

        result = ConversationResult(
            scenario_id=scenario.scenario_id,
            thread_id=thread_id,
            started_at=started_at,
            model_versions=self._get_model_versions(),
            config_flags=self._capture_config_flags(),
        )

        # Initialize session state
        session_state: Dict[str, Any] = {
            "thread_id": thread_id,
            "trip_inputs": initial_trip_inputs or {},
            "metadata": {
                "scenario_id": scenario.scenario_id,
                "test_run": True,
                **(metadata_tags or {}),
            },
        }

        total_start = asyncio.get_event_loop().time()

        for turn in scenario.turns:
            turn_start = asyncio.get_event_loop().time()

            try:
                response = await run_turn(
                    user_text=turn.user_message,
                    session_state=session_state,
                )

                turn_duration = (asyncio.get_event_loop().time() - turn_start) * 1000

                # Extract observability from session_state
                resp_session = response.get("session_state", {})

                # Capture LangSmith run ID for trace correlation
                turn_run_id = response.get("run_id")

                turn_result = TurnResult(
                    turn_number=turn.turn_number,
                    user_message=turn.user_message,
                    assistant_message=response.get("assistant_message", ""),
                    trip_inputs=response.get("trip_inputs", {}),
                    ready_to_generate=response.get("ready_to_generate", False),
                    branches=response.get("branches", []),
                    suggested_responses=response.get("suggested_responses", []),
                    errors=response.get("errors", []),
                    session_state=resp_session,
                    run_id=turn_run_id,
                    router_intent=resp_session.get("router_intent"),
                    strategy_topic=resp_session.get("strategy_topic"),
                    short_circuit_type=resp_session.get("short_circuit_type"),
                    llm_calls_made=resp_session.get("llm_calls_made", 0),
                    cache_hits=resp_session.get("cache_hits", 0),
                    confidence_routing=resp_session.get("confidence_routing"),
                    total_tokens=resp_session.get("total_tokens", 0),
                    node_tokens=resp_session.get("node_tokens", {}),
                    llm_time_ms=resp_session.get("llm_time_ms", 0.0),
                    duration_ms=turn_duration,
                )

                result.turns.append(turn_result)
                result.total_llm_calls += turn_result.llm_calls_made
                result.total_cache_hits += turn_result.cache_hits
                result.total_tokens += turn_result.total_tokens
                result.total_llm_time_ms += turn_result.llm_time_ms

                # Store run_id for trace correlation
                if turn_run_id:
                    result.run_ids.append(turn_run_id)

                # Update session state for next turn
                session_state = response.get("session_state", session_state)

                # Capture any errors
                if turn_result.errors:
                    result.errors_encountered.extend(turn_result.errors)

            except Exception as e:
                error_msg = f"Turn {turn.turn_number} failed: {str(e)}"
                result.errors_encountered.append(error_msg)

                # Create a partial turn result for the error
                turn_result = TurnResult(
                    turn_number=turn.turn_number,
                    user_message=turn.user_message,
                    assistant_message="",
                    trip_inputs={},
                    ready_to_generate=False,
                    branches=[],
                    suggested_responses=[],
                    errors=[error_msg],
                    session_state=session_state,
                )
                result.turns.append(turn_result)

        total_duration = (asyncio.get_event_loop().time() - total_start) * 1000
        result.total_duration_ms = total_duration
        result.completed_at = datetime.now(timezone.utc).isoformat()
        result.final_state = session_state

        return result

    async def execute_scenarios_batch(
        self,
        scenarios: List[ConversationScenario],
        parallel: bool = False,
        max_concurrent: int = 3,
    ) -> List[ConversationResult]:
        """
        Execute multiple scenarios.

        Args:
            scenarios: List of scenarios to execute
            parallel: Whether to run scenarios in parallel
            max_concurrent: Maximum concurrent executions if parallel=True

        Returns:
            List of ConversationResults
        """
        if not parallel:
            results = []
            for scenario in scenarios:
                result = await self.execute_scenario(scenario)
                results.append(result)
            return results

        # Parallel execution with semaphore
        semaphore = asyncio.Semaphore(max_concurrent)

        async def execute_with_limit(scenario: ConversationScenario):
            async with semaphore:
                return await self.execute_scenario(scenario)

        return await asyncio.gather(*[execute_with_limit(s) for s in scenarios])


async def execute_golden_scenarios(
    enable_langsmith: bool = True,
) -> List[ConversationResult]:
    """Execute all golden scenarios for regression testing."""
    from tests.e2e.scenario_generator import get_golden_scenarios

    executor = ConversationExecutor(enable_langsmith=enable_langsmith)
    scenarios = get_golden_scenarios()

    return await executor.execute_scenarios_batch(scenarios, parallel=False)
