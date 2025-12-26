"""
PR-E: Debug Utilities Module
============================

Extracted debug logging functions from plan_graph.py.

This module provides:
- _debug(): Conditional debug logging
- _debug_error(): Error logging with emoji prefix
- _debug_suggestions(): Suggestion logging for debug visibility
- safe_debug(): Guaranteed non-throwing debug wrapper
- safe_debug_error(): Guaranteed non-throwing error debug wrapper

All functions are non-fatal - they silently catch errors to prevent
debug code from crashing production.
"""

from __future__ import annotations

from typing import Any, List

from app.config import settings

# =============================================================================
# DEBUG LOGGING
# =============================================================================

# Cache the debug flag at import time for performance
_DEBUG_LOG = settings.debug_plan_messages


def is_debug_enabled() -> bool:
    """Check if debug logging is enabled."""
    return _DEBUG_LOG


def _debug(message: str, **kwargs: Any) -> None:
    """Print debug message if DEBUG_PLAN_MESSAGES is enabled.

    This function is designed to be non-fatal - any error during logging
    is silently caught to prevent debug code from crashing production.
    """
    if not _DEBUG_LOG:
        return
    try:
        # Truncate message if too long
        max_len = 2000
        if len(message) > max_len:
            message = message[:max_len] + "...(truncated)"

        # Safely format kwargs, handling any serialization errors
        extras_parts = []
        for k, v in kwargs.items():
            try:
                v_str = str(v)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "..."
                extras_parts.append(f"{k}={v_str}")
            except Exception:
                extras_parts.append(f"{k}=<unserializable>")
        extras = " ".join(extras_parts) if extras_parts else ""
        print(f"[PLAN_GRAPH DEBUG] {message} {extras}".strip())
    except Exception:
        # Never re-raise - debug logging must not crash production
        pass


def _debug_error(message: str, **kwargs: Any) -> None:
    """Print ERROR message - always visible and prominent.

    This function is designed to be non-fatal - any error during logging
    is silently caught to prevent debug code from crashing production.
    """
    if not _DEBUG_LOG:
        return
    try:
        # Truncate message if too long
        max_len = 2000
        if len(message) > max_len:
            message = message[:max_len] + "...(truncated)"

        # Safely format kwargs, handling any serialization errors
        extras_parts = []
        for k, v in kwargs.items():
            try:
                v_str = str(v)
                if len(v_str) > 200:
                    v_str = v_str[:200] + "..."
                extras_parts.append(f"{k}={v_str}")
            except Exception:
                extras_parts.append(f"{k}=<unserializable>")
        extras = " ".join(extras_parts) if extras_parts else ""
        print(f"[PLAN_GRAPH ERROR] ❌ {message} {extras}".strip())
    except Exception:
        # Never re-raise - debug logging must not crash production
        pass


def _debug_suggestions(suggestions: List[str], source: str = "") -> None:
    """Print user prompt suggestions for debug visibility.

    This function is designed to be non-fatal - any error during logging
    is silently caught to prevent debug code from crashing production.
    """
    if not _DEBUG_LOG:
        return
    try:
        src_tag = f" ({source})" if source else ""
        if suggestions:
            # Truncate each suggestion and limit count
            truncated = [s[:100] + "..." if len(s) > 100 else s for s in suggestions[:5]]
            suggestions_str = " | ".join(truncated)
            print(f"[PLAN_GRAPH DEBUG] 💡 Prompt suggestions{src_tag}: [{suggestions_str}]")
        else:
            print(f"[PLAN_GRAPH DEBUG] 💡 Prompt suggestions{src_tag}: (none)")
    except Exception:
        # Never re-raise - debug logging must not crash production
        pass


# =============================================================================
# SAFE DEBUG: Guaranteed non-throwing debug for use in safety wrappers
# =============================================================================


def safe_debug(message: str, **kwargs: Any) -> None:
    """
    Guaranteed non-throwing debug function for use inside @safe_node and recovery code.

    Unlike _debug(), this function wraps EVERYTHING in try/except including
    the initial condition check and all string formatting. Use this in places
    where even a debug failure could break critical recovery paths.
    """
    try:
        _debug(message, **kwargs)
    except Exception:
        # Absolutely never throw - this is the safety net
        pass


def safe_debug_error(message: str, **kwargs: Any) -> None:
    """Guaranteed non-throwing error debug for safety wrappers."""
    try:
        _debug_error(message, **kwargs)
    except Exception:
        pass
