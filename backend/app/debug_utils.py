"""
PR-E: Debug Utilities Module
============================

Consolidated debug logging for the planning graph.

DEBUG modes (set in .env or environment):
- DEBUG=off     - Zero output (production)
- DEBUG=demo    - Rich colorized agent-level logs only (for videos, with delay)
- DEBUG=full    - Rich colorized logs + verbose V2 DEBUG statements (no delay)
- DEBUG=compact - Structured compact logs with token tracking (recommended for dev)

Both demo and full modes use the same colorized rich output for agent-level
logs (log, log_phase, log_tokens, log_complete). The difference is:
- demo: includes configurable delay (RICH_DEMO_DELAY_MS) for video recording
- full: no delay, plus verbose _debug/_debug_log statements
- compact: structured symbol-prefixed logs with token/cost tracking

All functions are non-fatal - they silently catch errors to prevent
debug code from crashing production.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

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

    Returns: 'demo', 'full', 'compact', or 'off'
    """
    mode = os.getenv("DEBUG", "off").lower().strip()
    if mode in ("demo", "full", "compact"):
        return mode
    # Legacy support
    if os.getenv("RICH_DEMO_LOGS", "0") == "1":
        return "demo"
    if os.getenv("DEBUG_PLAN_MESSAGES", "").lower() in ("true", "1", "yes"):
        return "full"
    return "off"


def _get_demo_delay() -> float:
    """Get demo delay in seconds. Only non-zero when DEBUG=demo."""
    if get_debug_mode() != "demo":
        return 0.0
    return float(os.getenv("RICH_DEMO_DELAY_MS", "100")) / 1000.0


# =============================================================================
# TOKEN TRACKING DATA CLASSES
# =============================================================================


@dataclass
class TokenUsage:
    """Track token usage for LLM calls."""

    prompt: int = 0
    completion: int = 0

    @property
    def total(self) -> int:
        return self.prompt + self.completion

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            prompt=self.prompt + other.prompt,
            completion=self.completion + other.completion,
        )

    def __str__(self) -> str:
        return f"p={self.prompt} c={self.completion} tot={self.total}"


@dataclass
class RequestMetrics:
    """Track metrics for entire graph execution."""

    start_time: float
    node_tokens: Dict[str, TokenUsage] = field(default_factory=dict)
    node_durations: Dict[str, int] = field(default_factory=dict)
    model_usage: Dict[str, TokenUsage] = field(default_factory=dict)

    @property
    def total_tokens(self) -> TokenUsage:
        """Sum tokens across all nodes."""
        result = TokenUsage()
        for usage in self.node_tokens.values():
            result = result + usage
        return result

    def add_model_usage(self, model: str, usage: TokenUsage) -> None:
        """Track usage per model."""
        if model not in self.model_usage:
            self.model_usage[model] = TokenUsage()
        self.model_usage[model] = self.model_usage[model] + usage


# =============================================================================
# COMPACT LOGGER CLASS
# =============================================================================


class CompactLogger:
    """Structured, compact logging with token tracking for DEBUG=compact mode."""

    SYMBOLS = {
        "cache_hit": "✅",
        "cache_miss": "❌",
        "llm_call": "🤖",
        "api_call": "🌐",
        "constraint": "⚖️",
        "specialist": "🎯",
        "tokens": "🔢",
    }

    MODEL_PRICING = {  # Per 1M tokens (USD)
        "gpt-4o": {"prompt": 2.50, "completion": 10.00},
        "gpt-4o-mini": {"prompt": 0.15, "completion": 0.60},
    }

    # Cost thresholds from environment
    COST_WARNING_THRESHOLD = float(os.getenv("COST_THRESHOLD_WARNING", "0.10"))
    COST_CRITICAL_THRESHOLD = float(os.getenv("COST_THRESHOLD_CRITICAL", "1.00"))

    def __init__(self, name: str, metrics: Optional[RequestMetrics] = None):
        self.logger = logging.getLogger(f"app.{name}")
        self._is_compact = get_debug_mode() == "compact"
        self.metrics = metrics
        self.current_node_tokens = TokenUsage()

    def node_start(self, node: str, **kwargs: Any) -> None:
        """Log node entry (only in compact mode)."""
        if not self._is_compact:
            return
        try:
            params = self._format_params(kwargs)
            _safe_print(f"▶ {node:12s} | {params}")
            self.current_node_tokens = TokenUsage()
        except Exception:
            pass

    def node_end(self, node: str, duration_ms: int, **kwargs: Any) -> None:
        """Log node exit (only in compact mode)."""
        if not self._is_compact:
            # Still track metrics even if not in compact mode
            if self.metrics:
                self.metrics.node_tokens[node] = self.current_node_tokens
                self.metrics.node_durations[node] = duration_ms
            return
        try:
            params = self._format_params(kwargs)
            if self.current_node_tokens.total > 0:
                params += f" | 🔢 {self.current_node_tokens}"
            _safe_print(f"✓ {node:12s} | {duration_ms:4d}ms | {params}")
            if self.metrics:
                self.metrics.node_tokens[node] = self.current_node_tokens
                self.metrics.node_durations[node] = duration_ms
        except Exception:
            pass

    def llm_call(
        self, model: str, prompt_tokens: int, completion_tokens: int, **kwargs: Any
    ) -> None:
        """Log LLM call with token usage."""
        usage = TokenUsage(prompt=prompt_tokens, completion=completion_tokens)
        self.current_node_tokens = self.current_node_tokens + usage
        if self.metrics:
            self.metrics.add_model_usage(model, usage)
        if not self._is_compact:
            return
        try:
            cost = self._calculate_cost(model, usage)
            params = self._format_params(kwargs)
            if params:
                params = f" {params}"
            _safe_print(
                f"  🤖 {model:20s} | "
                f"p={prompt_tokens:4d} c={completion_tokens:4d} tot={usage.total:4d} "
                f"${cost:.4f}{params}"
            )
        except Exception:
            pass

    def llm_call_from_response(self, response: Any, purpose: str = "") -> None:
        """Log LLM call directly from LangChain response object."""
        try:
            metadata = response.response_metadata
            usage = metadata.get("token_usage", {})
            model = metadata.get("model_name", "unknown")
            self.llm_call(
                model=model,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                purpose=purpose,
            )
        except Exception:
            pass

    def event(self, category: str, message: str, **kwargs: Any) -> None:
        """Log an event (only in compact mode)."""
        if not self._is_compact:
            return
        try:
            symbol = self.SYMBOLS.get(category, "•")
            params = self._format_params(kwargs)
            _safe_print(f"  {symbol} {message:40s} | {params}")
        except Exception:
            pass

    def state_change(self, label: str, old: Any, new: Any) -> None:
        """Log state transitions (only in compact mode)."""
        if not self._is_compact:
            return
        if old != new:
            try:
                status = "(CHANGED)" if old and new else "(SET)"
                _safe_print(f"🔄 {label:20s} | {old} → {new} {status}")
            except Exception:
                pass

    def batch_update(self, label: str, updates: Dict[str, Any]) -> None:
        """Log multiple fields in one line (only in compact mode)."""
        if not self._is_compact:
            return
        try:
            params = self._format_params(updates)
            _safe_print(f"📝 {label:20s} | {params}")
        except Exception:
            pass

    def critical(self, message: str) -> None:
        """Log critical events (always outputs regardless of mode)."""
        try:
            _safe_print(f"⚠️  {message}")
        except Exception:
            pass

    def separator(self, title: str = "") -> None:
        """Visual section divider (only in compact mode)."""
        if not self._is_compact:
            return
        try:
            if title:
                _safe_print(f"\n{'─' * 20} {title} {'─' * 20}")
            else:
                _safe_print("─" * 60)
        except Exception:
            pass

    def request_summary(self) -> None:
        """Log cumulative metrics with cost alerts (only in compact mode)."""
        if not self._is_compact or not self.metrics:
            return
        try:
            total = self.metrics.total_tokens
            duration = sum(self.metrics.node_durations.values())

            # Calculate total cost
            total_cost = 0.0
            for model, usage in self.metrics.model_usage.items():
                total_cost += self._calculate_cost(model, usage)

            self.separator("REQUEST SUMMARY")
            _safe_print(
                f"🔢 TOKENS          | "
                f"p={total.prompt:5d} c={total.completion:5d} tot={total.total:5d} "
                f"${total_cost:.4f}"
            )

            # Cost threshold alerts
            if total_cost > self.COST_CRITICAL_THRESHOLD:
                self.critical(
                    f"High cost request: ${total_cost:.2f}! "
                    f"(threshold: ${self.COST_CRITICAL_THRESHOLD})"
                )
            elif total_cost > self.COST_WARNING_THRESHOLD:
                _safe_print(
                    f"⚠️  Elevated cost: ${total_cost:.4f} "
                    f"(threshold: ${self.COST_WARNING_THRESHOLD})"
                )

            _safe_print(f"⏱️  DURATION        | {duration:5d}ms ({duration / 1000:.2f}s)")

            # Per-model breakdown
            if len(self.metrics.model_usage) > 1:
                _safe_print("📊 MODEL BREAKDOWN:")
                for model, usage in self.metrics.model_usage.items():
                    cost = self._calculate_cost(model, usage)
                    _safe_print(
                        f"  • {model:20s} | p={usage.prompt:4d} c={usage.completion:4d} ${cost:.4f}"
                    )
        except Exception:
            pass

    def _calculate_cost(self, model: str, usage: TokenUsage) -> float:
        """Calculate cost in USD for token usage."""
        if model not in self.MODEL_PRICING:
            return 0.0
        pricing = self.MODEL_PRICING[model]
        prompt_cost = (usage.prompt / 1_000_000) * pricing["prompt"]
        completion_cost = (usage.completion / 1_000_000) * pricing["completion"]
        return prompt_cost + completion_cost

    @staticmethod
    def _format_params(params: Dict[str, Any]) -> str:
        """Format parameters as key=value pairs."""
        items = []
        for k, v in params.items():
            if v is None:
                continue
            try:
                v_str = str(v)
                if len(v_str) > 40:
                    v_str = v_str[:37] + "..."
                items.append(f"{k}={v_str}")
            except Exception:
                items.append(f"{k}=<error>")
        return " ".join(items)


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
# CONVERSATION TURN LOGGING (shown in full mode - clear delimiters)
# =============================================================================


def log_user_input(message: str, request_id: str = "") -> None:
    """
    Log user input with clear visual delimiters.
    Only shown in full mode. Makes conversation starts easy to find in logs.
    """
    if get_debug_mode() != "full":
        return
    try:
        req_tag = f" [{request_id}]" if request_id else ""
        _console.print()
        _console.print("[bold green]" + "=" * 70 + "[/bold green]")
        _console.print(f"[bold green]>>> USER INPUT{req_tag}[/bold green]")
        _console.print("[bold green]" + "=" * 70 + "[/bold green]")
        # Show full message (don't truncate user input - it's important)
        _console.print(f"[white]{message}[/white]")
        _console.print("[bold green]" + "-" * 70 + "[/bold green]")
        _console.print()
    except Exception:
        pass


def log_llm_output(message: str, request_id: str = "", truncate_at: int = 2000) -> None:
    """
    Log LLM output with clear visual delimiters.
    Only shown in full mode. Makes conversation ends easy to find in logs.
    """
    if get_debug_mode() != "full":
        return
    try:
        req_tag = f" [{request_id}]" if request_id else ""
        display_msg = message
        truncated = False
        if len(message) > truncate_at:
            display_msg = message[:truncate_at]
            truncated = True

        _console.print()
        _console.print("[bold cyan]" + "=" * 70 + "[/bold cyan]")
        _console.print(f"[bold cyan]<<< LLM OUTPUT{req_tag}[/bold cyan]")
        _console.print("[bold cyan]" + "=" * 70 + "[/bold cyan]")
        _console.print(f"[white]{display_msg}[/white]")
        if truncated:
            _console.print(f"[dim]... (truncated, {len(message)} chars total)[/dim]")
        _console.print("[bold cyan]" + "-" * 70 + "[/bold cyan]")
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


def _debug_node_start(node_name: str, emoji: str, **inputs: Any) -> None:
    """Log node start with inputs. Only shown in full mode."""
    if get_debug_mode() != "full":
        return
    try:
        inputs_str = " ".join(f"{k}={_truncate(v)}" for k, v in inputs.items())
        _safe_print(f"[DEBUG] {emoji} {node_name.upper()} START | {inputs_str}")
    except Exception:
        pass


def _debug_node_end(node_name: str, emoji: str, **outputs: Any) -> None:
    """Log node end with outputs. Only shown in full mode."""
    if get_debug_mode() != "full":
        return
    try:
        outputs_str = " ".join(f"{k}={_truncate(v)}" for k, v in outputs.items())
        _safe_print(f"[DEBUG] {emoji} {node_name.upper()} END | {outputs_str}")
    except Exception:
        pass


def _debug_log(message: str, **kwargs: Any) -> None:
    """General debug message. Only shown in full mode."""
    if get_debug_mode() != "full":
        return
    try:
        extras = " ".join(f"{k}={_truncate(v)}" for k, v in kwargs.items()) if kwargs else ""
        _safe_print(f"[DEBUG] {message} {extras}".strip())
    except Exception:
        pass


# =============================================================================
# NODE TIMING UTILITIES
# =============================================================================

# Global dict to track node start times
_node_start_times: dict[str, float] = {}


def _debug_node_timer_start(node_name: str) -> None:
    """Start timing a node. Call at node entry."""
    _node_start_times[node_name] = time.time()


def _debug_node_timer_end(node_name: str, emoji: str = "", **outputs: Any) -> None:
    """
    End timing and log node duration.
    Call at node exit (replaces _debug_node_end for timed nodes).
    """
    if get_debug_mode() != "full":
        return
    try:
        start_time = _node_start_times.pop(node_name, None)
        if start_time:
            duration_ms = (time.time() - start_time) * 1000
            outputs_str = " ".join(f"{k}={_truncate(v)}" for k, v in outputs.items())
            _safe_print(
                f"[DEBUG] {emoji} {node_name.upper()} END | "
                f"duration={duration_ms:.0f}ms | {outputs_str}"
            )
        else:
            # No start time recorded, just log outputs
            outputs_str = " ".join(f"{k}={_truncate(v)}" for k, v in outputs.items())
            _safe_print(f"[DEBUG] {emoji} {node_name.upper()} END | {outputs_str}")
    except Exception:
        pass


class NodeTimer:
    """
    Context manager for timing node execution.

    Usage:
        with NodeTimer("specialist", "🤿") as timer:
            # node code
            timer.set_outputs(activities=3, constraints=2)
    """

    def __init__(self, node_name: str, emoji: str = ""):
        self.node_name = node_name
        self.emoji = emoji
        self.start_time: float = 0
        self.outputs: dict[str, Any] = {}

    def __enter__(self) -> "NodeTimer":
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if get_debug_mode() != "full":
            return
        try:
            duration_ms = (time.time() - self.start_time) * 1000
            outputs_str = " ".join(f"{k}={_truncate(v)}" for k, v in self.outputs.items())
            status = "ERROR" if exc_type else "COMPLETE"
            _safe_print(
                f"[DEBUG] {self.emoji} {self.node_name.upper()} {status} | "
                f"duration={duration_ms:.0f}ms | {outputs_str}"
            )
        except Exception:
            pass

    def set_outputs(self, **kwargs: Any) -> None:
        """Set outputs to be logged at node end."""
        self.outputs.update(kwargs)


def _debug_itinerary(message: str, **kwargs: Any) -> None:
    """Print itinerary builder debug message. Shown in full AND compact modes."""
    mode = get_debug_mode()
    if mode not in ("full", "compact"):
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
        _safe_print(f"[ITINERARY] {message} {extras}".strip())
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
    logging.getLogger("app.planner.nodes").setLevel(logging.CRITICAL)

    # Telemetry trace logger (suppress structured trace events)
    logging.getLogger("planner.trace").setLevel(logging.CRITICAL)
