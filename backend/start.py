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

import logging
import sys

# Load .env before importing anything else
from pathlib import Path

from dotenv import load_dotenv

env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


def main():
    import uvicorn

    from app.config import settings

    is_prod = "--prod" in sys.argv
    log_level = "debug" if settings.debug_mode == "full" else "error"

    # Configure root logger so application loggers (app.*) output INFO/DEBUG
    # to stderr. Without this, uvicorn only adds handlers for its own loggers
    # and Python's lastResort handler only captures WARNING+, so all
    # logger.info() / logger.debug() calls from app.* are silently dropped.
    if log_level == "debug":
        logging.basicConfig(
            level=logging.INFO,
            format="%(levelname)s:%(name)s:%(message)s",
            stream=sys.stderr,
        )

    print(f"Starting Nomadic Backend (DEBUG={settings.debug_mode}, log_level={log_level})")

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
