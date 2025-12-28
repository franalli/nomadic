"""
Specialist Groundedness - Guardrail for preventing invented details.

Contains:
- Groundedness warning generation for tile-based specialists
- Tracking of groundedness blocks for observability

Extracted from specialist_main.py as part of P3 module extraction.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Set

if TYPE_CHECKING:
    from app.plan_graph import GraphState

# Specialists that rely on tile data for grounded responses
TILE_BASED_SPECIALISTS: Set[str] = {"hotels", "flights", "activities"}

# Phrases that indicate user is asking for options/recommendations
OPTION_REQUEST_PHRASES = (
    "recommend",
    "suggest",
    "options",
    "choices",
    "what about",
    "show me",
    "find me",
    "any good",
    "best",
    "where to stay",
    "which hotel",
    "which flight",
    "which activit",
)


def check_groundedness_guardrail(
    state: "GraphState",
    specialist_name: str,
    available_options: str,
) -> str:
    """
    Check if groundedness warning should be added to prompt.

    This guardrail prevents the LLM from inventing specific names, prices,
    or details when no verified options (tiles) are available.

    Args:
        state: Current graph state
        specialist_name: Name of the specialist (e.g., "hotels", "flights")
        available_options: The available_options context string

    Returns:
        Groundedness warning string to append to prompt, or empty string
    """
    from app.debug_utils import _debug
    from app.plan_graph import _increment_state_counter

    if specialist_name not in TILE_BASED_SPECIALISTS:
        return ""

    options_empty = not available_options.strip()
    options_invalid = available_options.strip() and "error" in available_options.lower()

    # Check if user asked for options or specialist is in recommendation mode
    user_text_lower = (state.user_text or "").lower()
    user_asked_for_options = any(phrase in user_text_lower for phrase in OPTION_REQUEST_PHRASES)
    pre_core_mode = state.metadata.get("pre_core_mode") if state.metadata else False

    # In pre_core_mode, the specialist focuses on collecting missing fields,
    # NOT on providing recommendations. So we should NOT trigger groundedness
    # warnings in pre_core_mode.
    recommendation_mode = user_asked_for_options and not pre_core_mode

    if not ((options_empty or options_invalid) and recommendation_mode):
        return ""

    # Determine reason for blocking
    if options_empty:
        block_reason = "no_tiles"
    elif options_invalid:
        block_reason = "tiles_invalid"
    else:
        block_reason = "tiles_stale"

    groundedness_warning = (
        "\n\nGROUNDEDNESS CONSTRAINT\n"
        "No verified options are currently available for this category.\n"
        "DO NOT invent or fabricate specific names, prices, or details.\n"
        "Instead, acknowledge the request and explain that specific options "
        "are being searched for or will be available shortly.\n"
    )

    # Track with proper tags for observability
    _increment_state_counter("invented_detail_block_count")
    _debug(
        "[GROUNDEDNESS] Blocking potential invention due to missing tiles",
        intent=specialist_name,
        node=f"specialist:{specialist_name}",
        pre_core_mode=pre_core_mode,
        reason=block_reason,
        user_asked_for_options=user_asked_for_options,
    )

    # Store tags in metadata for downstream analysis
    if state.metadata is None:
        state.metadata = {}
    groundedness_blocks = state.metadata.get("groundedness_blocks", [])
    groundedness_blocks.append(
        {
            "intent": specialist_name,
            "node": f"specialist:{specialist_name}",
            "pre_core_mode": pre_core_mode,
            "reason": block_reason,
            "turn": state.turn_number,
        }
    )
    state.metadata["groundedness_blocks"] = groundedness_blocks

    return groundedness_warning
