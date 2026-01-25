# logger.py
"""
Rich Console Logging for Demo Videos.

Provides colorized, aligned output for the V2 planning graph.

DEBUG modes (set in .env or environment):
- DEBUG=demo  - Clean rich logs only (for videos)
- DEBUG=full  - Everything (V2 DEBUG + rich logs)
- DEBUG=off   - Minimal logging (production)
"""

import os
import time

from rich.console import Console
from rich.theme import Theme

# "Systems Engineering" color palette
custom_theme = Theme(
    {
        "timestamp": "dim white",
        "orchestrator": "bold blue",
        "router": "bold cyan",
        "agent": "bold magenta",
        "architect": "bold magenta",
        "specialist": "bold yellow",
        "data": "cyan",
        "constraint": "bold yellow",
        "guard": "bold yellow",
        "solver": "bold orange1",
        "synth": "bold blue",
        "success": "bold green",
        "error": "bold red",
        "tokens": "dim cyan",
        "api": "dim white",
    }
)

console = Console(theme=custom_theme)


def get_debug_mode() -> str:
    """Get current debug mode from environment.

    Returns: 'demo', 'full', or 'off'
    """
    mode = os.getenv("DEBUG", "off").lower().strip()
    if mode in ("demo", "full"):
        return mode
    # Legacy support for RICH_DEMO_LOGS
    if os.getenv("RICH_DEMO_LOGS", "0") == "1":
        return "demo"
    return "off"


def is_demo_mode() -> bool:
    """Check if demo mode is active (clean rich logs only)."""
    return get_debug_mode() == "demo"


def is_full_mode() -> bool:
    """Check if full debug mode is active (all logs)."""
    return get_debug_mode() == "full"


def is_logging_enabled() -> bool:
    """Check if any logging is enabled (demo or full)."""
    return get_debug_mode() in ("demo", "full")


# Delay for demo mode (configurable)
DEMO_DELAY = float(os.getenv("RICH_DEMO_DELAY_MS", "300")) / 1000.0


def log(tag: str, message: str, data: str | None = None, sleep: float | None = None):
    """
    Colorized log output for demo videos.

    Args:
        tag: Component name (e.g., "ARCHITECT", "GUARD", "SPECIALIST")
        message: The action being performed
        data: Optional extra info (e.g., "destination=Bali")
        sleep: Override delay in seconds (default: DEMO_DELAY if demo mode)
    """
    mode = get_debug_mode()

    if mode == "off":
        return  # Silent in production

    if mode == "full":
        # Simple print format for full mode
        if data:
            print(f"[{tag}] {message} | {data}")
        else:
            print(f"[{tag}] {message}")
        return

    # Demo mode: Rich colorized output
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
    elif "SUCCESS" in tag_upper:
        style = "success"
    elif "ERROR" in tag_upper:
        style = "error"
    elif "ROUTER" in tag_upper or "ORCHESTR" in tag_upper:
        style = "router"
    elif "TOKEN" in tag_upper:
        style = "tokens"
    elif "API" in tag_upper:
        style = "api"

    # Print main line
    console.print(f"[{style}]{formatted_tag}[/{style}] {message}")

    # Print data indented if exists
    if data:
        console.print(f"{' ' * 17}[data]└─ {data}[/data]")

    # Demo delay
    delay = sleep if sleep is not None else DEMO_DELAY
    if delay > 0:
        time.sleep(delay)


def log_phase(phase: str, title: str):
    """Print a phase header box."""
    mode = get_debug_mode()

    if mode == "off":
        return

    if mode == "full":
        print(f"\n{'='*60}\n{phase}: {title}\n{'='*60}")
        return

    # Demo mode: Rich box
    console.print()
    console.print("=" * 60)
    console.print(f"   [bold]{phase}: {title}[/bold]")
    console.print("=" * 60)
    time.sleep(DEMO_DELAY)


def log_tokens(component: str, prompt: int, completion: int, total: int):
    """Log token usage."""
    log(
        "TOKENS",
        f"{component} LLM call",
        data=f"prompt={prompt} | completion={completion} | total={total}",
    )


def log_complete(tiles: int, strategy_sections: int, view_state: str):
    """Log graph completion summary."""
    mode = get_debug_mode()

    if mode == "off":
        return

    if mode == "full":
        print(f"\n[COMPLETE] Tiles: {tiles} | Strategy: {strategy_sections} | View: {view_state}")
        return

    # Demo mode: Rich box
    console.print()
    console.print("=" * 60)
    console.print("   [success]GRAPH COMPLETE[/success]")
    console.print(f"   Tiles: {tiles} | Strategy: {strategy_sections} | View: {view_state}")
    console.print("=" * 60)
