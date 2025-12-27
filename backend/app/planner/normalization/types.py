"""
Normalization Types - Tier 3 Module Extraction.

This module defines types used by the normalization system.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional


@dataclass
class NormalizationError:
    """
    Structured error from normalization with severity level.

    Attributes:
        field: The field name that had the error
        message: Human-readable error message
        severity: 'blocking' for blocking issues, 'warning' for recoverable, 'info' for notes
        original_value: The original value that caused the error
        code: Machine-readable error code (e.g., DATE_AMBIGUOUS_YEAR)
    """

    field: str
    message: str
    severity: Literal["blocking", "warning", "info"]
    original_value: Any = None
    code: Optional[str] = None
