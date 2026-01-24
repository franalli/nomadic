"""E2E test helpers - hermetic multi-turn runner + failure artifacts.

This module provides utilities for running multi-turn conversations
through the plan graph and dumping debug artifacts on test failure.

Usage:
    from tests.langgraph.e2e_helpers import run_multi_turn, dump_failure

    state, turns = await run_multi_turn([
        "I want to go to Japan",
        "Next month for 10 days",
        "Solo trip",
    ])

    # Assert on state/metadata, NOT assistant_message
    assert turns[-1]["strategy_stage"] >= 2
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

ARTIFACT_DIR = Path(__file__).parent.parent.parent / "test_artifacts"


@dataclass
class E2EArtifact:
    """Debug bundle dumped on test failure."""

    test_name: str
    timestamp: str
    turns: List[dict]
    hard_failures: List[str]
    final_state: dict

    def dump(self) -> Path:
        ARTIFACT_DIR.mkdir(exist_ok=True)
        filename = f"{self.test_name}_{self.timestamp.replace(':', '-').replace('.', '-')}.json"
        path = ARTIFACT_DIR / filename
        path.write_text(json.dumps(asdict(self), indent=2, default=str))
        return path


def dump_failure(
    test_name: str,
    turns: List[dict],
    failures: List[str],
    final_state: Any,
) -> Path:
    """Dump artifact bundle on test failure for debugging."""
    artifact = E2EArtifact(
        test_name=test_name,
        timestamp=datetime.now().isoformat(),
        turns=turns,
        hard_failures=failures,
        final_state=_serialize(final_state),
    )
    return artifact.dump()


def _serialize(obj: Any) -> dict:
    """Safely serialize state/result for artifact."""
    if obj is None:
        return {}
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_serialize(v) for v in obj]
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if hasattr(obj, "__dict__"):
        return {k: str(v) for k, v in obj.__dict__.items()}
    return str(obj)


async def run_multi_turn(user_inputs: List[str]) -> tuple[dict, List[dict]]:
    """Run multiple turns through plan graph, return final result + turn log.

    Uses FakeLLM when run under @pytest.mark.e2e (hermetic mode).
    Assertions should use state/metadata fields, NOT assistant_message.

    Args:
        user_inputs: List of user messages to send sequentially.

    Returns:
        Tuple of (final_result_dict, list_of_turn_snapshots)
    """
    from app.plan_graph import run_turn

    turns = []
    session_state: Optional[dict] = None

    for user_input in user_inputs:
        result = await run_turn(user_input, session_state)

        # Extract metadata from session_state
        metadata = result.get("session_state", {}).get("metadata", {})

        # Log STATE/METADATA fields for deterministic assertions
        turns.append(
            {
                "user": user_input,
                # Metadata fields for assertions
                "strategy_stage": metadata.get("strategy_stage"),
                "strategy_topic": result.get("session_state", {}).get("strategy_topic"),
                "executed_strategy_topics": metadata.get("executed_strategy_topics"),
                "pending_strategy_topics": metadata.get("pending_strategy_topics"),
                "question_target": metadata.get("question_target"),
                "reorchestrate_strategies": metadata.get("reorchestrate_strategies"),
                "force_strategy_topics": metadata.get("force_strategy_topics"),
                # For debugging only (not for assertions)
                "_response_preview": (result.get("assistant_message") or "")[:100],
            }
        )

        # Pass session_state to next turn
        session_state = result.get("session_state")

    return result, turns


def get_metadata(result: dict) -> dict:
    """Extract metadata dict from run_turn result."""
    return result.get("session_state", {}).get("metadata", {})


def get_tiles(result: dict) -> List[dict]:
    """Extract tiles from result with stable fields for assertions.

    Returns list of dicts with: id, content_hash, source_agent, category, title
    """
    # Tiles may be in different locations depending on result structure
    branches = result.get("branches") or result.get("session_state", {}).get("branches", [])

    tiles = []
    for branch in branches:
        if isinstance(branch, dict):
            branch_tiles = branch.get("tiles", [])
            for tile in branch_tiles:
                if isinstance(tile, dict):
                    tiles.append(
                        {
                            "id": tile.get("id"),
                            "content_hash": tile.get("content_hash"),
                            "source_agent": tile.get("source_agent"),
                            "category": tile.get("category"),
                            "title": tile.get("title"),  # For debugging, not assertions
                        }
                    )

    return tiles
