"""
Trace summarizer for normalizing conversation traces before evaluation.

Extracts deterministic summaries from LangSmith traces or local ConversationResults,
normalizing data to reduce noise and cost before passing to LLM evaluators.
"""

from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from tests.e2e.conversation_executor import ConversationResult

logger = logging.getLogger(__name__)

# Delay before fetching traces from LangSmith (eventual consistency)
LANGSMITH_TRACE_DELAY_SECONDS = 2.0


@dataclass
class ToolOutput:
    """Normalized tool/node output from the conversation."""

    node_name: str
    turn_number: int
    output_type: str  # hotels, flights, activities, etc.
    data: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_name": self.node_name,
            "turn_number": self.turn_number,
            "output_type": self.output_type,
            "data": self.data,
        }


@dataclass
class StateTransition:
    """Represents a state change between turns."""

    turn_number: int
    field: str
    before: Any
    after: Any
    valid: bool = True
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "turn_number": self.turn_number,
            "field": self.field,
            "before": self.before,
            "after": self.after,
            "valid": self.valid,
            "notes": self.notes,
        }


@dataclass
class TranscriptEntry:
    """A single entry in the conversation transcript."""

    turn_number: int
    role: str  # user or assistant
    content: str

    def to_dict(self) -> Dict[str, str | int]:
        return {
            "turn": self.turn_number,
            "role": self.role,
            "content": self.content,
        }


@dataclass
class NodeTraceDetails:
    """Details about a specific node execution from LangSmith."""

    node_name: str
    run_id: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    outputs: Dict[str, Any] = field(default_factory=dict)
    latency_ms: float = 0.0
    token_count: int = 0
    status: str = "success"  # success, error, timeout
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_name": self.node_name,
            "run_id": self.run_id,
            "inputs": self.inputs,
            "outputs": self.outputs,
            "latency_ms": self.latency_ms,
            "token_count": self.token_count,
            "status": self.status,
            "error_message": self.error_message,
        }


@dataclass
class LangSmithTraceDetails:
    """Detailed trace information fetched from LangSmith."""

    run_id: str
    turn_number: int
    total_latency_ms: float = 0.0
    total_tokens: int = 0
    node_traces: List[NodeTraceDetails] = field(default_factory=list)
    raw_trace: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "turn_number": self.turn_number,
            "total_latency_ms": self.total_latency_ms,
            "total_tokens": self.total_tokens,
            "node_traces": [n.to_dict() for n in self.node_traces],
        }


@dataclass
class TraceSummary:
    """Normalized summary of a conversation trace for evaluation."""

    scenario_id: str
    thread_id: str

    # Conversation transcript
    transcript: List[TranscriptEntry] = field(default_factory=list)

    # Final state snapshot
    final_trip_inputs: Dict[str, Any] = field(default_factory=dict)
    final_branches: List[Dict[str, Any]] = field(default_factory=list)

    # Key tool outputs across the conversation
    tool_outputs: List[ToolOutput] = field(default_factory=list)

    # State transitions for node-level evaluation
    state_transitions: List[StateTransition] = field(default_factory=list)

    # Routing decisions
    routing_decisions: List[Dict[str, Any]] = field(default_factory=list)

    # Error and retry information
    errors: List[str] = field(default_factory=list)
    retries: List[Dict[str, Any]] = field(default_factory=list)

    # Metadata
    total_turns: int = 0
    total_llm_calls: int = 0
    total_cache_hits: int = 0
    total_duration_ms: float = 0.0

    # Model versions used
    model_versions: Dict[str, str] = field(default_factory=dict)

    # LangSmith trace details (populated when fetched from LangSmith)
    langsmith_traces: List[LangSmithTraceDetails] = field(default_factory=list)
    run_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "scenario_id": self.scenario_id,
            "thread_id": self.thread_id,
            "transcript": [t.to_dict() for t in self.transcript],
            "final_trip_inputs": self.final_trip_inputs,
            "final_branches": self.final_branches,
            "tool_outputs": [t.to_dict() for t in self.tool_outputs],
            "state_transitions": [s.to_dict() for s in self.state_transitions],
            "routing_decisions": self.routing_decisions,
            "errors": self.errors,
            "retries": self.retries,
            "total_turns": self.total_turns,
            "total_llm_calls": self.total_llm_calls,
            "total_cache_hits": self.total_cache_hits,
            "total_duration_ms": self.total_duration_ms,
            "model_versions": self.model_versions,
            "langsmith_traces": [t.to_dict() for t in self.langsmith_traces],
            "run_ids": self.run_ids,
        }

    def get_transcript_text(self) -> str:
        """Get the full transcript as formatted text."""
        lines = []
        for entry in self.transcript:
            role = "User" if entry.role == "user" else "Assistant"
            lines.append(f"[Turn {entry.turn_number}] {role}: {entry.content}")
        return "\n\n".join(lines)

    def get_extracted_destinations(self) -> List[str]:
        """Get the final extracted destinations."""
        return self.final_trip_inputs.get("destinations", [])

    def get_extracted_dates(self) -> Dict[str, Optional[str]]:
        """Get the final extracted dates."""
        return {
            "start_date": self.final_trip_inputs.get("start_date"),
            "end_date": self.final_trip_inputs.get("end_date"),
        }


class TraceSummarizer:
    """Summarizes conversation traces for evaluation."""

    def __init__(
        self,
        include_state_transitions: bool = True,
        include_tool_outputs: bool = True,
        max_transcript_length: int = 10000,
    ):
        self.include_state_transitions = include_state_transitions
        self.include_tool_outputs = include_tool_outputs
        self.max_transcript_length = max_transcript_length

    def summarize_local(self, result: ConversationResult) -> TraceSummary:
        """
        Summarize a local ConversationResult (without LangSmith).

        This is used when running tests without LangSmith or for faster local testing.
        """
        summary = TraceSummary(
            scenario_id=result.scenario_id,
            thread_id=result.thread_id,
            total_turns=len(result.turns),
            total_llm_calls=result.total_llm_calls,
            total_cache_hits=result.total_cache_hits,
            total_duration_ms=result.total_duration_ms,
            model_versions=result.model_versions,
            errors=result.errors_encountered.copy(),
        )

        # Build transcript
        for turn in result.turns:
            # User message
            summary.transcript.append(
                TranscriptEntry(
                    turn_number=turn.turn_number,
                    role="user",
                    content=turn.user_message,
                )
            )
            # Assistant message
            if turn.assistant_message:
                summary.transcript.append(
                    TranscriptEntry(
                        turn_number=turn.turn_number,
                        role="assistant",
                        content=turn.assistant_message,
                    )
                )

        # Final state
        if result.turns:
            last_turn = result.turns[-1]
            summary.final_trip_inputs = last_turn.trip_inputs
            summary.final_branches = last_turn.branches

        # Routing decisions
        for turn in result.turns:
            if turn.router_intent:
                summary.routing_decisions.append(
                    {
                        "turn": turn.turn_number,
                        "intent": turn.router_intent,
                        "strategy_topic": turn.strategy_topic,
                        "short_circuit": turn.short_circuit_type,
                        "confidence_routing": turn.confidence_routing,
                    }
                )

        # State transitions (compare consecutive turns)
        if self.include_state_transitions and len(result.turns) > 1:
            for i in range(1, len(result.turns)):
                prev_turn = result.turns[i - 1]
                curr_turn = result.turns[i]
                transitions = self._compute_state_transitions(
                    prev_turn.trip_inputs,
                    curr_turn.trip_inputs,
                    curr_turn.turn_number,
                )
                summary.state_transitions.extend(transitions)

        # Tool outputs from branches
        if self.include_tool_outputs:
            for turn in result.turns:
                if turn.branches:
                    for branch in turn.branches:
                        summary.tool_outputs.append(
                            ToolOutput(
                                node_name="branch_postprocess",
                                turn_number=turn.turn_number,
                                output_type="branch",
                                data=branch,
                            )
                        )

        return summary

    def _compute_state_transitions(
        self,
        before: Dict[str, Any],
        after: Dict[str, Any],
        turn_number: int,
    ) -> List[StateTransition]:
        """Compute state transitions between two trip_inputs snapshots."""
        transitions = []

        # Fields to track
        tracked_fields = [
            "destinations",
            "origin",
            "start_date",
            "end_date",
            "adults",
            "children",
            "budget",
            "currency",
            "booking_types",
            "flight_settings",
            "hotel_settings",
            "activity_settings",
            "transport_settings",
        ]

        for tracked_field in tracked_fields:
            before_val = before.get(tracked_field)
            after_val = after.get(tracked_field)

            if before_val != after_val:
                transitions.append(
                    StateTransition(
                        turn_number=turn_number,
                        field=tracked_field,
                        before=before_val,
                        after=after_val,
                        valid=self._validate_transition(field, before_val, after_val),
                    )
                )

        return transitions

    def _validate_transition(
        self,
        field: str,
        before: Any,
        after: Any,
    ) -> bool:
        """Validate that a state transition is legal."""
        # Destinations should only grow or be explicitly reset
        if field == "destinations":
            if isinstance(before, list) and isinstance(after, list):
                # Allow adding destinations
                if len(after) >= len(before):
                    return True
                # Allow explicit reset (empty list)
                if len(after) == 0:
                    return True
                # Removing destinations without reset is suspicious
                return False

        # Dates should be valid ISO format if set
        if field in ("start_date", "end_date"):
            if after is not None:
                try:
                    datetime.fromisoformat(after)
                except ValueError:
                    return False

        # Budget should be positive
        if field == "budget":
            if after is not None and (not isinstance(after, (int, float)) or after < 0):
                return False

        return True

    async def summarize_from_langsmith(
        self,
        run_id: str,
        turn_number: int = 0,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
    ) -> Optional[LangSmithTraceDetails]:
        """
        Fetch trace details for a single run from LangSmith.

        Args:
            run_id: The LangSmith run ID or thread_id correlator to fetch.
                   This can be either a UUID run_id or the turn_thread_id
                   returned by run_turn() for trace correlation.
            turn_number: The conversation turn this trace belongs to
            api_key: Optional API key override
            api_url: Optional API URL override (for EU endpoint)

        Returns:
            LangSmithTraceDetails with node-level trace information, or None if unavailable
        """
        try:
            from langsmith import Client
        except ImportError:
            logger.warning("langsmith package not installed, skipping trace fetch")
            return None

        api_key = api_key or os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
        api_url = api_url or os.getenv("LANGSMITH_ENDPOINT") or os.getenv("LANGCHAIN_ENDPOINT")

        if not api_key:
            logger.warning("LangSmith API key not configured, skipping trace fetch")
            return None

        # Wait for eventual consistency
        await asyncio.sleep(LANGSMITH_TRACE_DELAY_SECONDS)

        try:
            client = Client(api_key=api_key, api_url=api_url)

            # Try to fetch the run directly by ID
            run = None
            try:
                run = client.read_run(run_id)
            except Exception as e:
                # If direct lookup fails (e.g., run_id is a correlation string, not UUID),
                # try searching by thread tag
                logger.debug(f"Direct run lookup failed for {run_id}: {e}, trying tag search")
                try:
                    project_name = os.getenv("LANGCHAIN_PROJECT", "default")
                    # Search for runs with matching thread tag
                    runs = list(
                        client.list_runs(
                            project_name=project_name,
                            filter=f'has(tags, "thread:{run_id.split("_")[0]}")',
                            limit=1,
                        )
                    )
                    if runs:
                        run = runs[0]
                        logger.debug(f"Found run via tag search: {run.id}")
                except Exception as search_e:
                    logger.debug(f"Tag search also failed: {search_e}")

            if run is None:
                logger.warning(f"Could not find LangSmith run for {run_id}")
                return None

            # Calculate latency
            total_latency_ms = 0.0
            if run.end_time and run.start_time:
                total_latency_ms = (run.end_time - run.start_time).total_seconds() * 1000

            # Create trace details
            trace_details = LangSmithTraceDetails(
                run_id=run_id,
                turn_number=turn_number,
                total_latency_ms=total_latency_ms,
                total_tokens=run.total_tokens or 0,
                raw_trace={
                    "name": run.name,
                    "status": run.status,
                    "inputs": run.inputs,
                    "outputs": run.outputs,
                },
            )

            # Fetch child runs for node-level details
            try:
                child_runs = list(
                    client.list_runs(
                        run_ids=[run_id],
                        is_root=False,
                    )
                )

                for child in child_runs:
                    child_latency = 0.0
                    if child.end_time and child.start_time:
                        child_latency = (child.end_time - child.start_time).total_seconds() * 1000

                    node_trace = NodeTraceDetails(
                        node_name=child.name or "unknown",
                        run_id=str(child.id),
                        inputs=child.inputs or {},
                        outputs=child.outputs or {},
                        latency_ms=child_latency,
                        token_count=child.total_tokens or 0,
                        status="error" if child.error else "success",
                        error_message=child.error if child.error else None,
                    )
                    trace_details.node_traces.append(node_trace)

            except Exception as e:
                logger.warning(f"Failed to fetch child runs for {run_id}: {e}")

            return trace_details

        except Exception as e:
            logger.warning(f"Failed to fetch trace {run_id} from LangSmith: {e}")
            return None

    async def enrich_summary_with_langsmith(
        self,
        summary: TraceSummary,
        run_ids: List[str],
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
    ) -> TraceSummary:
        """
        Enrich a local TraceSummary with LangSmith trace details.

        Fetches trace information for each run_id and adds it to the summary.

        Args:
            summary: The local TraceSummary to enrich
            run_ids: List of LangSmith run IDs (one per turn)
            api_key: Optional API key override
            api_url: Optional API URL override

        Returns:
            The enriched TraceSummary
        """
        summary.run_ids = run_ids

        for turn_number, run_id in enumerate(run_ids, start=1):
            if not run_id:
                continue

            trace_details = await self.summarize_from_langsmith(
                run_id=run_id,
                turn_number=turn_number,
                api_key=api_key,
                api_url=api_url,
            )

            if trace_details:
                summary.langsmith_traces.append(trace_details)

        return summary


def summarize_for_evaluation(
    result: ConversationResult,
    max_length: int = 8000,
) -> str:
    """
    Create a compact text summary suitable for LLM evaluation.

    This produces a structured text that can be included in an evaluation prompt
    without exceeding token limits.
    """
    summarizer = TraceSummarizer(
        include_state_transitions=True,
        include_tool_outputs=True,
        max_transcript_length=max_length,
    )

    summary = summarizer.summarize_local(result)

    # Build compact text representation
    lines = [
        f"# Conversation Summary: {summary.scenario_id}",
        "",
        "## Transcript",
        summary.get_transcript_text(),
        "",
        "## Final Trip Inputs",
    ]

    # Format trip inputs
    trip = summary.final_trip_inputs
    if trip.get("destinations"):
        lines.append(f"- Destinations: {', '.join(trip['destinations'])}")
    if trip.get("origin"):
        lines.append(f"- Origin: {trip['origin']}")
    if trip.get("start_date"):
        lines.append(f"- Start Date: {trip['start_date']}")
    if trip.get("end_date"):
        lines.append(f"- End Date: {trip['end_date']}")
    if trip.get("adults"):
        lines.append(f"- Adults: {trip['adults']}")
    if trip.get("children"):
        lines.append(f"- Children: {trip['children']}")
    if trip.get("budget"):
        lines.append(f"- Budget: {trip['budget']} {trip.get('currency', 'USD')}")

    lines.extend(
        [
            "",
            "## Routing Decisions",
        ]
    )
    for rd in summary.routing_decisions:
        lines.append(
            f"- Turn {rd['turn']}: {rd['intent']}"
            + (f" (strategy: {rd['strategy_topic']})" if rd.get("strategy_topic") else "")
        )

    if summary.errors:
        lines.extend(
            [
                "",
                "## Errors Encountered",
            ]
        )
        for err in summary.errors:
            lines.append(f"- {err}")

    lines.extend(
        [
            "",
            "## Metrics",
            f"- Total Turns: {summary.total_turns}",
            f"- LLM Calls: {summary.total_llm_calls}",
            f"- Cache Hits: {summary.total_cache_hits}",
            f"- Duration: {summary.total_duration_ms:.0f}ms",
        ]
    )

    text = "\n".join(lines)

    # Truncate if too long
    if len(text) > max_length:
        text = text[: max_length - 100] + "\n\n... [truncated]"

    return text
