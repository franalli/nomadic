"""
Data module - Curated content and demo data.

This module contains:
- demo_curation.py: Golden Path curated content for hero destinations
"""

from .demo_curation import (
    DEMO_MANIFEST,
    get_curated_content,
    get_hero_destinations,
    is_hero_destination,
)

__all__ = [
    "DEMO_MANIFEST",
    "get_curated_content",
    "get_hero_destinations",
    "is_hero_destination",
]
