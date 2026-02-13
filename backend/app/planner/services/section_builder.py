"""
Section builder service — centralises strategy-section CRUD that was duplicated
across vertical_specialist.py, local_expert.py, and plan_graph.py.

Public API
----------
- upsert_section(metadata, section, *, mode)
- mark_topic_executed(metadata, topic)
- build_specialist_section(...)
- build_local_expert_section(...)
- sort_sections_anchor_first(sections)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Anchor-first sort (moved from plan_graph.py _sort_sections_anchor_first)
# ---------------------------------------------------------------------------

_ANCHOR_TYPES = {"local_expert", "general"}


def sort_sections_anchor_first(sections: list) -> list:
    """Ensure local_expert/general is always at index 0 (anchor rule).

    This fixes the ordering flip bug where filter+append pattern
    reverses section order when local_expert runs twice.
    """
    anchors = [s for s in sections if s.get("specialist_type") in _ANCHOR_TYPES]
    others = [s for s in sections if s.get("specialist_type") not in _ANCHOR_TYPES]
    return anchors + others


# ---------------------------------------------------------------------------
# Upsert + executed-topic tracking
# ---------------------------------------------------------------------------


def upsert_section(metadata: dict, section: dict, *, mode: str = "appendable") -> None:
    """Init-if-missing, filter-by-type, insert/append, anchor-sort.

    Replaces the duplicated 4-line pattern in vertical_specialist.py and
    local_expert.py, plus the SINGLETON/APPENDABLE logic in plan_graph.py.

    Args:
        metadata: ``state.metadata`` dict (mutated in place).
        section:  The section dict to upsert.
        mode:     ``"singleton"`` — replace at index 0 (General Agent).
                  ``"appendable"`` — deduplicate by specialist_type, append.
    """
    if "strategy_sections" not in metadata:
        metadata["strategy_sections"] = []

    specialist_type = section.get("specialist_type", "")
    metadata["strategy_sections"] = [
        s for s in metadata["strategy_sections"] if s.get("specialist_type") != specialist_type
    ]

    if mode == "singleton":
        metadata["strategy_sections"].insert(0, section)
    else:
        metadata["strategy_sections"].append(section)

    metadata["strategy_sections"] = sort_sections_anchor_first(metadata["strategy_sections"])


def mark_topic_executed(metadata: dict, topic: str) -> None:
    """Deduplicating append to ``executed_strategy_topics``."""
    executed = metadata.get("executed_strategy_topics", [])
    if topic not in executed:
        executed = list(executed)  # copy before mutate
        executed.append(topic)
        metadata["executed_strategy_topics"] = executed


# ---------------------------------------------------------------------------
# Section dict builders (pure data — no state mutation)
# ---------------------------------------------------------------------------


def build_specialist_section(
    *,
    topic: str,
    destination: Optional[str],
    start_date: Optional[str],
    end_date: Optional[str],
    feasibility_status: str,
    feasibility_reason: Optional[str],
    alternative_suggestion: Optional[str],
    constraints: List[Dict[str, Any]],
    content_added: List[Dict[str, Any]],
    enhancements: List[Any],
    hero_image: Optional[str],
    day_pref: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a specialist strategy section dict.

    Extracted from vertical_specialist.py lines 2178-2200.
    """
    return {
        "id": f"specialist_{topic}",
        "title": f"{topic.title()} Specialist",
        "specialist_type": topic,
        "subtitle": destination,  # For cache comparison
        # Cache invalidation keys: must match destination AND dates AND day_pref
        "_cache_dates": f"{start_date}:{end_date}",
        "_cache_day_pref": day_pref,
        "feasibility_status": feasibility_status,
        "feasibility_reason": feasibility_reason,
        "alternative_suggestion": alternative_suggestion,
        "constraints_applied": constraints,
        "content_added": content_added,
        "content_blocks": content_added,
        "hero_image": hero_image,  # Hero banner for niche specialist layout
        "impact_areas": [topic.title(), "Safety", "Activities"],
        # Required fields for StrategySection
        "principles": [],
        "must_dos": [],
        "optional_upgrades": enhancements[:3] if enhancements else [],
        "logistics_notes": [],
        "bullets": [],
    }


def build_local_expert_section(
    *,
    destination: str,
    one_liner: str,
    bullets: List[str],
    must_dos: List[str],
    logistics_notes: List[str],
    constraints_applied: List[Dict[str, Any]],
    content_added: List[Dict[str, Any]],
    gallery_images: List[Dict[str, Any]],
    travel_intelligence: Dict[str, Any],
) -> Dict[str, Any]:
    """Build a local-expert strategy section dict.

    Extracted from local_expert.py lines 1541-1561.
    """
    return {
        "id": "strategy_local_expert",
        "specialist_type": "local_expert",
        "title": f"{destination} Trip Overview",
        "one_liner": one_liner,
        "bullets": bullets,
        "principles": [],
        "must_dos": must_dos,
        "optional_upgrades": [],
        "logistics_notes": logistics_notes,
        "constraints_applied": constraints_applied,
        "content_added": content_added,
        "content_blocks": content_added,
        "impact_areas": ["Logistics", "Timing", "Culture"],
        "destination_gallery": gallery_images,  # "Vibe Trio" images for Magazine Layout
        # Comprehensive 12-category travel intelligence
        "travel_intelligence": travel_intelligence,
    }
