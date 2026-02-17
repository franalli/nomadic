# backend/app/planner/hashing.py
"""
Stable hashing utilities for deterministic cache keys and reproducible tests.

PR5: Stable hashing utilities - replaces Python's built-in hash() with
stable alternatives that produce consistent results across processes.

Problem:
- Python's hash() uses PYTHONHASHSEED randomization by default
- This makes cache keys non-reproducible across test runs
- Can cause flaky tests and hard-to-debug cache misses

Solution:
- Use blake2s for fast, stable hashing
- Provide specialized canonicalization for common types
- Ban hash() in planner code via CI test
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Optional, Sequence


def stable_hash(value: Any, *, length: int = 16) -> str:
    """
    Generate a stable hash string for any value.

    Uses blake2s with canonical JSON serialization for consistency.
    Result is stable across Python processes and restarts.

    Args:
        value: Any JSON-serializable value
        length: Length of hex output (default 16, max 64)

    Returns:
        Hex string of specified length

    Example:
        >>> stable_hash("hello")
        '9c22ff5f21f0b81b'  # pragma: allowlist secret
        >>> stable_hash({"b": 2, "a": 1})  # Keys are sorted
        '4f4e3e0b2f9c8d1a'  # pragma: allowlist secret
    """
    if length < 1 or length > 64:
        raise ValueError(f"length must be 1-64, got {length}")

    # Canonicalize to JSON with sorted keys
    try:
        serialized = json.dumps(value, sort_keys=True, default=str, ensure_ascii=True)
    except (TypeError, ValueError):
        # Fallback for non-serializable types
        serialized = repr(value)

    # Use blake2s for speed (faster than sha256 for short inputs)
    digest = hashlib.blake2s(serialized.encode("utf-8"), digest_size=32).hexdigest()
    return digest[:length]


def stable_hash_short(value: Any) -> str:
    """
    Generate a short 8-character stable hash.

    Convenience wrapper for compact display in logs and traces.
    """
    return stable_hash(value, length=8)


def canonicalize_destinations(destinations: Optional[Sequence[str]]) -> str:
    """
    Create a canonical string representation of destinations for cache keys.

    Ensures consistent ordering regardless of input order.

    Args:
        destinations: List of destination strings, or None

    Returns:
        Sorted, joined string for cache key component

    Example:
        >>> canonicalize_destinations(["Paris", "London"])
        "London|Paris"
        >>> canonicalize_destinations(None)
        ""
    """
    if not destinations:
        return ""

    # Normalize: lowercase, strip, sort
    normalized = sorted(d.strip().lower() for d in destinations if d and d.strip())
    return "|".join(normalized)


def make_cache_key(*parts: Any) -> str:
    """
    Build a stable cache key from multiple parts.

    Parts are canonicalized and joined with '::'.

    Args:
        *parts: Any number of key components

    Returns:
        Stable cache key string

    Example:
        >>> make_cache_key("router", "v6", ["Paris", "London"])
        "router::v6::london|paris"
    """
    key_parts = []
    for part in parts:
        if part is None:
            key_parts.append("")
        elif isinstance(part, str):
            key_parts.append(part)
        elif isinstance(part, (list, tuple)):
            # Treat as destinations/fields list
            if all(isinstance(x, str) for x in part):
                key_parts.append(canonicalize_destinations(part))
            else:
                key_parts.append(stable_hash_short(part))
        elif isinstance(part, dict):
            key_parts.append(stable_hash_short(part))
        else:
            key_parts.append(str(part))

    return "::".join(key_parts)


def field_hash(value: str) -> str:
    """Stable hash for selective regeneration change detection.

    Canonical implementation — used by state_serde and regen_strategy
    to detect which trip fields changed between requests.
    """
    return hashlib.sha256((value or "").encode()).hexdigest()[:12]


# Mapping for ban enforcement
BANNED_PATTERNS = [
    r"(?<![_a-zA-Z])hash\(",  # hash( not preceded by identifier char
]

REPLACEMENT_SUGGESTIONS = {
    "hash(": "Use stable_hash(), stable_hash_int(), or stable_hash_index() instead",
}
