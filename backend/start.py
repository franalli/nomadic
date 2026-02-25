#!/usr/bin/env python3
"""
Nomadic Backend Startup Script

Respects DEBUG mode from .env for uvicorn logging:
- DEBUG=off     - Minimal logging (--log-level error)
- DEBUG=compact - Minimal logging (--log-level error)
- DEBUG=full    - Full logging (--log-level debug)

Usage:
    python start.py          # Development with hot reload
    python start.py --prod   # Production mode (no reload)
"""

import os
import sys

# Load .env before importing anything else
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


def get_log_level() -> str:
    """Get uvicorn log level based on DEBUG mode."""
    debug_mode = os.getenv("DEBUG", "off").lower().strip()
    if debug_mode == "full":
        return "debug"
    # For compact and off modes, suppress uvicorn's warnings (including WatchFiles)
    return "error"


def main():
    import uvicorn

    from app.config import settings

    is_prod = "--prod" in sys.argv
    log_level = get_log_level()

    print(f"Starting Nomadic Backend (DEBUG={os.getenv('DEBUG', 'off')}, log_level={log_level})")

    uvicorn.run(
        "app.main:app",
        host=settings.backend_host,
        port=settings.backend_port,
        reload=not is_prod,
        log_level=log_level,
        h11_max_incomplete_event_size=1_048_576,  # 1 MB h11 incomplete event buffer
    )


if __name__ == "__main__":
    main()
