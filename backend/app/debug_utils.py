"""
PR-E: Debug Utilities Module
============================

Consolidated debug logging for the V2 planning graph.

DEBUG modes (set in .env or environment):
- DEBUG=off   - Zero output (production)
- DEBUG=demo  - Rich colorized agent-level logs only (for videos, with delay)
- DEBUG=full  - Rich colorized logs + verbose V2 DEBUG statements (no delay)

Both demo and full modes use the same colorized rich output for agent-level
logs (log, log_phase, log_tokens, log_complete). The difference is:
- demo: includes configurable delay (RICH_DEMO_DELAY_MS) for video recording
- full: no delay, plus verbose _debug/_debug_v2 statements

All functions are non-fatal - they silently catch errors to prevent
debug code from crashing production.
"""

from __future__ import annotations

import os
import time
from typing import Any, List

from rich.console import Console
from rich.theme import Theme

# =============================================================================
# DEBUG MODE CONFIGURATION
# =============================================================================

# "Systems Engineering" color palette for demo mode
_THEME = Theme(
    {
        "orchestrator": "bold blue",
        "router": "bold cyan",
        "architect": "bold magenta",
        "specialist": "bold yellow",
        "guard": "bold yellow",
        "constraint": "bold yellow",
        "solver": "bold orange1",
        "synth": "bold blue",
        "success": "bold green",
        "safe": "bold green",
        "blocked": "bold red",
        "error": "bold red",
        "tokens": "dim cyan",
        "api": "dim white",
        "data": "cyan",
    }
)

_console = Console(theme=_THEME)


def get_debug_mode() -> str:
    """Get current debug mode from environment.

    Returns: 'demo', 'full', or 'off'
    """
    mode = os.getenv("DEBUG", "off").lower().strip()
    if mode in ("demo", "full"):
        return mode
    # Legacy support
    if os.getenv("RICH_DEMO_LOGS", "0") == "1":
        return "demo"
    if os.getenv("DEBUG_PLAN_MESSAGES", "").lower() in ("true", "1", "yes"):
        return "full"
    return "off"


def is_demo_mode() -> bool:
    """Check if demo mode is active (clean agent-level logs only)."""
    return get_debug_mode() == "demo"


def is_full_mode() -> bool:
    """Check if full debug mode is active (all logs)."""
    return get_debug_mode() == "full"


def is_debug_enabled() -> bool:
    """Check if any debug logging is enabled."""
    return get_debug_mode() in ("demo", "full")


def _get_demo_delay() -> float:
    """Get demo delay in seconds. Only non-zero when DEBUG=demo."""
    if get_debug_mode() != "demo":
        return 0.0
    return float(os.getenv("RICH_DEMO_DELAY_MS", "100")) / 1000.0


# =============================================================================
# AGENT-LEVEL LOGGING (shown in both demo and full modes)
# =============================================================================


def log(tag: str, message: str, data: str | None = None, sleep: float | None = None):
    """
    Agent-level log output. Shown in both demo and full modes with rich colorization.

    Args:
        tag: Component name (e.g., "ARCHITECT", "GUARD", "SPECIALIST")
        message: The action being performed
        data: Optional extra info (e.g., "destination=Bali")
        sleep: Override delay in seconds (default: _get_demo_delay() in demo mode only)
    """
    mode = get_debug_mode()

    if mode == "off":
        return

    # Both demo and full use rich colorized output
    try:
        formatted_tag = f"[{tag}]".ljust(16)

        # Choose style based on tag content
        style = "white"
        tag_upper = tag.upper()
        if "AGENT" in tag_upper or "ARCHITECT" in tag_upper:
            style = "architect"
        elif "SPECIALIST" in tag_upper:
            style = "specialist"
        elif "CONSTRAINT" in tag_upper or "GUARD" in tag_upper:
            style = "guard"
        elif "SOLVER" in tag_upper:
            style = "solver"
        elif "SYNTH" in tag_upper:
            style = "synth"
        elif "SAFE" in tag_upper or "SUCCESS" in tag_upper:
            style = "safe"
        elif "BLOCKED" in tag_upper or "ERROR" in tag_upper:
            style = "blocked"
        elif "ROUTER" in tag_upper or "ORCHESTR" in tag_upper:
            style = "router"
        elif "TOKEN" in tag_upper:
            style = "tokens"
        elif "API" in tag_upper:
            style = "api"

        _console.print(f"[{style}]{formatted_tag}[/{style}] {message}")

        if data:
            _console.print(f"{' ' * 17}[data]└─ {data}[/data]")

        # Demo delay (only in demo mode, not full)
        if mode == "demo":
            delay = sleep if sleep is not None else _get_demo_delay()
            if delay > 0:
                time.sleep(delay)
    except Exception:
        pass


def log_phase(phase: str, title: str):
    """Print a phase header box. Shown in both demo and full modes with rich colorization."""
    mode = get_debug_mode()

    if mode == "off":
        return

    # Both demo and full use rich colorized output
    try:
        _console.print()
        _console.print()
        _console.print("[bold cyan]" + "─" * 50 + "[/bold cyan]")
        _console.print(f"   [bold]{phase}: {title}[/bold]")
        _console.print("[bold cyan]" + "─" * 50 + "[/bold cyan]")
        # Demo delay (only in demo mode, not full)
        if mode == "demo":
            time.sleep(_get_demo_delay())
    except Exception:
        pass


def log_tokens(component: str, prompt: int, completion: int, total: int):
    """Log token usage. Shown in both demo and full modes."""
    log(
        "TOKENS",
        f"{component} LLM call",
        data=f"prompt={prompt} | completion={completion} | total={total}",
    )


def log_complete(tiles: int, strategy_sections: int, view_state: str):
    """Log graph completion summary. Shown in both demo and full modes with rich colorization."""
    mode = get_debug_mode()

    if mode == "off":
        return

    # Both demo and full use rich colorized output
    try:
        _console.print()
        _console.print()
        _console.print("[success]" + "=" * 50 + "[/success]")
        _console.print("[success]       ✓ PLAN OPTIMIZED[/success]")
        _console.print("[success]" + "=" * 50 + "[/success]")
        _console.print(f"   Tiles: {tiles} | Strategy: {strategy_sections}")
        _console.print(f"   View: {view_state}")
        _console.print()
    except Exception:
        pass


# =============================================================================
# VERBOSE DEBUG LOGGING (only shown in full mode)
# =============================================================================


def _safe_print(msg: str) -> None:
    """Print with fallback for Unicode encoding issues on Windows."""
    try:
        print(msg)
    except UnicodeEncodeError:
        ascii_msg = msg.encode("ascii", "replace").decode("ascii")
        print(ascii_msg)


def _truncate(value: Any, max_len: int = 100) -> str:
    """Truncate value for debug output."""
    try:
        s = str(value)
        if len(s) > max_len:
            return s[:max_len] + "..."
        return s
    except Exception:
        return "<unserializable>"


def _debug_v2_node_start(node_name: str, emoji: str, **inputs: Any) -> None:
    """Log V2 node start with inputs. Only shown in full mode."""
    if get_debug_mode() != "full":
        return
    try:
        inputs_str = " ".join(f"{k}={_truncate(v)}" for k, v in inputs.items())
        _safe_print(f"[V2 DEBUG] {emoji} {node_name.upper()} START | {inputs_str}")
    except Exception:
        pass


def _debug_v2_node_end(node_name: str, emoji: str, **outputs: Any) -> None:
    """Log V2 node end with outputs. Only shown in full mode."""
    if get_debug_mode() != "full":
        return
    try:
        outputs_str = " ".join(f"{k}={_truncate(v)}" for k, v in outputs.items())
        _safe_print(f"[V2 DEBUG] {emoji} {node_name.upper()} END | {outputs_str}")
    except Exception:
        pass


def _debug_v2(message: str, **kwargs: Any) -> None:
    """General V2 debug message. Only shown in full mode."""
    if get_debug_mode() != "full":
        return
    try:
        extras = " ".join(f"{k}={_truncate(v)}" for k, v in kwargs.items()) if kwargs else ""
        _safe_print(f"[V2 DEBUG] {message} {extras}".strip())
    except Exception:
        pass


def _debug(message: str, **kwargs: Any) -> None:
    """Print debug message. Only shown in full mode."""
    if get_debug_mode() != "full":
        return
    try:
        max_len = 2000
        if len(message) > max_len:
            message = message[:max_len] + "...(truncated)"

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
        _safe_print(f"[DEBUG] {message} {extras}".strip())
    except Exception:
        pass


def _debug_error(message: str, **kwargs: Any) -> None:
    """Print ERROR message. Only shown in full mode."""
    if get_debug_mode() != "full":
        return
    try:
        max_len = 2000
        if len(message) > max_len:
            message = message[:max_len] + "...(truncated)"

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
        _safe_print(f"[ERROR] {message} {extras}".strip())
    except Exception:
        pass


def _debug_suggestions(suggestions: List[str], source: str = "") -> None:
    """Print user prompt suggestions. Only shown in full mode."""
    if get_debug_mode() != "full":
        return
    try:
        src_tag = f" ({source})" if source else ""
        if suggestions:
            truncated = [s[:100] + "..." if len(s) > 100 else s for s in suggestions[:5]]
            suggestions_str = " | ".join(truncated)
            _safe_print(f"[DEBUG] Prompt suggestions{src_tag}: [{suggestions_str}]")
        else:
            _safe_print(f"[DEBUG] Prompt suggestions{src_tag}: (none)")
    except Exception:
        pass


# =============================================================================
# SAFE DEBUG: Guaranteed non-throwing wrappers
# =============================================================================


def safe_debug(message: str, **kwargs: Any) -> None:
    """Guaranteed non-throwing debug function."""
    try:
        _debug(message, **kwargs)
    except Exception:
        pass


def safe_debug_error(message: str, **kwargs: Any) -> None:
    """Guaranteed non-throwing error debug."""
    try:
        _debug_error(message, **kwargs)
    except Exception:
        pass


# =============================================================================
# LOGGING CONFIGURATION (for demo mode cleanup)
# =============================================================================


def configure_demo_logging():
    """
    Configure logging for demo/off modes.

    Suppresses:
    - ALL Python warnings (UserWarning, RuntimeWarning, DeprecationWarning)
    - HTTP access logs (uvicorn.access)
    - Uvicorn error logs (uvicorn.error)
    - OpenAI/LangChain schema warnings
    - Other noisy loggers

    Call this at app startup. Only applies when DEBUG=demo or DEBUG=off.
    """
    import logging
    import warnings

    mode = get_debug_mode()

    # Only suppress in demo and off modes (full mode shows everything)
    if mode == "full":
        return

    # =========================================================================
    # NUCLEAR OPTION: Suppress ALL Python warnings
    # =========================================================================
    warnings.filterwarnings("ignore")

    # =========================================================================
    # Suppress noisy loggers
    # =========================================================================
    # Uvicorn logs
    logging.getLogger("uvicorn.access").setLevel(logging.CRITICAL)
    logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)

    # Watchfiles (uvicorn's file watcher)
    logging.getLogger("watchfiles").setLevel(logging.CRITICAL)
    logging.getLogger("watchfiles.main").setLevel(logging.CRITICAL)

    # HTTP client logs
    logging.getLogger("httpx").setLevel(logging.CRITICAL)
    logging.getLogger("httpcore").setLevel(logging.CRITICAL)

    # OpenAI/LangChain logs (including schema validation errors)
    logging.getLogger("openai").setLevel(logging.CRITICAL)
    logging.getLogger("langchain").setLevel(logging.CRITICAL)
    logging.getLogger("langchain_core").setLevel(logging.CRITICAL)
    logging.getLogger("langchain_openai").setLevel(logging.CRITICAL)

    # Pydantic warnings
    logging.getLogger("pydantic").setLevel(logging.CRITICAL)

    # App-level loggers (suppress warnings/errors from our code in demo mode)
    logging.getLogger("app").setLevel(logging.CRITICAL)
    logging.getLogger("app.planner").setLevel(logging.CRITICAL)
    logging.getLogger("app.planner.nodes_v2").setLevel(logging.CRITICAL)

    # Telemetry trace logger (suppress structured trace events)
    logging.getLogger("planner.trace").setLevel(logging.CRITICAL)
