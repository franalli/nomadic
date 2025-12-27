"""
Parse Provenance Tracking - Tier 4 Module Extraction.

This module provides precedence-based tracking for how data was extracted/parsed
from user input. It uses write-once semantics where higher precedence sources
cannot be overwritten by lower ones.

Precedence order (higher wins):
    cached (5) > deterministic (4) > template (3) > codegen (2) > llm (1) > unknown (0)

Usage:
    from app.planner.parsing.provenance import (
        set_parse_provenance_once,
        finalize_parse_provenance,
        get_parse_provenance,
        PARSE_PROVENANCE_PRECEDENCE,
    )

    # Set provenance (returns True if accepted, False if blocked by higher precedence)
    set_parse_provenance_once(state, "deterministic", "lqa_prepass")

    # At end of turn, finalize to prevent further writes
    final = finalize_parse_provenance(state)

    # Query current provenance
    current = get_parse_provenance(state)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from app.debug_utils import _debug

if TYPE_CHECKING:
    from app.plan_graph import GraphState


# =============================================================================
# PARSE PROVENANCE PRECEDENCE
# =============================================================================
# Higher values take precedence. Once set to a higher value, cannot be downgraded.

PARSE_PROVENANCE_PRECEDENCE = {
    "cached": 5,
    "deterministic": 4,
    "template": 3,
    "codegen": 2,
    "llm": 1,
    "unknown": 0,
}


def set_parse_provenance_once(
    state: "GraphState",
    provenance: str,
    source_node: str,
) -> bool:
    """
    Set parse provenance with precedence enforcement.

    Parse provenance tracks how data was EXTRACTED/PARSED from user input.
    Only upgrades provenance (higher precedence wins).
    Returns True if provenance was set/upgraded, False if blocked.

    Args:
        state: Graph state
        provenance: New provenance value (cached, deterministic, template, codegen, llm, unknown)
        source_node: Node setting the provenance (for debugging)

    Returns:
        True if provenance was set, False if blocked by higher precedence
    """
    # Check if finalized
    if state.metadata.get("parse_provenance_finalized"):
        _debug(
            "PARSE_PROVENANCE_BLOCKED_FINALIZED",
            attempted=provenance,
            source_node=source_node,
            final_value=state.metadata.get("parse_provenance"),
        )
        return False

    current = state.metadata.get("parse_provenance", "unknown")
    current_precedence = PARSE_PROVENANCE_PRECEDENCE.get(current, 0)
    new_precedence = PARSE_PROVENANCE_PRECEDENCE.get(provenance, 0)

    if new_precedence > current_precedence:
        state.metadata["parse_provenance"] = provenance
        state.metadata["parse_provenance_source_node"] = source_node
        _debug(
            "PARSE_PROVENANCE_SET",
            old=current,
            new=provenance,
            source_node=source_node,
        )
        return True
    else:
        _debug(
            "PARSE_PROVENANCE_BLOCKED_PRECEDENCE",
            attempted=provenance,
            current=current,
            source_node=source_node,
        )
        return False


def finalize_parse_provenance(state: "GraphState") -> str:
    """
    Finalize parse provenance at end of turn. Subsequent writes are blocked.

    Should be called at end of run_turn() after all processing complete.

    Returns:
        Final parse provenance value
    """
    state.metadata["parse_provenance_finalized"] = True
    final = state.metadata.get("parse_provenance", "unknown")
    _debug(
        "PARSE_PROVENANCE_FINALIZED",
        value=final,
        source_node=state.metadata.get("parse_provenance_source_node"),
    )
    return final


def set_parse_provenance(state: "GraphState", provenance: str) -> None:
    """
    Set the parse provenance (how data was extracted from user input).

    DEPRECATED: Use set_parse_provenance_once() for precedence enforcement.
    This function is kept for backwards compatibility but now delegates
    to set_parse_provenance_once() with "compat:set_parse_provenance" as the source.

    Valid values:
    - "cached": Data from cache
    - "template": Template-based extraction
    - "deterministic": Deterministic code path (regex, pattern matching)
    - "codegen": Code-generated extraction
    - "llm": LLM-based extraction
    """
    set_parse_provenance_once(state, provenance, "compat:set_parse_provenance")


def get_parse_provenance(state: "GraphState") -> Optional[str]:
    """Get the parse provenance if set (how data was extracted from user input)."""
    return state.metadata.get("parse_provenance")
