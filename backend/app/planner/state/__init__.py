"""
State Package - P1 Module Extraction.

This package contains state management utilities for the planner.

Exports:
    StateWriter: Class for enforced SSoT state mutations

Usage:
    from app.planner.state import StateWriter
"""

from app.planner.state.writer import StateWriter

__all__ = [
    "StateWriter",
]
