"""
Normalization Package - Tier 3 Full Extraction.

This package contains the unified normalization logic for trip inputs,
extracted from plan_graph.py for better organization and testability.

Modules:
    types: NormalizationError dataclass
    date: DateNormalizer class, DateProvenance dataclass, normalize_str helper
    trip_inputs: TripInputNormalizer class

Usage:
    from app.planner.normalization import (
        NormalizationError,
        DateNormalizer,
        DateProvenance,
        TripInputNormalizer,
        normalize_str,
    )

    normalizer = DateNormalizer()
    iso_date = normalizer.normalize("next week")
    start, end = normalizer.parse_date_range("December 20-27")

    trip_normalizer = TripInputNormalizer(date_normalizer=normalizer)
    updates, errors = trip_normalizer.normalize_all(trip_inputs, deltas)
"""

from app.planner.normalization.date import (
    DateNormalizer,
    DateProvenance,
    _normalize_str,  # backward compat alias
    normalize_str,
)
from app.planner.normalization.trip_inputs import TripInputNormalizer
from app.planner.normalization.types import NormalizationError

__all__ = [
    "NormalizationError",
    "DateNormalizer",
    "DateProvenance",
    "TripInputNormalizer",
    "normalize_str",
    "_normalize_str",
]
