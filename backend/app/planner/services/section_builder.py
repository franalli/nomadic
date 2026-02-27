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
    skill_level: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a specialist strategy section dict.

    Extracted from vertical_specialist.py lines 2178-2200.
    """
    return {
        "id": f"specialist_{topic}",
        "title": f"{topic.title()} Specialist",
        "specialist_type": topic,
        "subtitle": destination,  # For cache comparison
        # Cache invalidation keys: must match destination AND dates AND day_pref AND skill_level
        "_cache_dates": f"{start_date}:{end_date}",
        "_cache_day_pref": day_pref,
        "_cache_skill_level": skill_level,
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
    principles: Optional[List[str]] = None,
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
        "principles": principles if principles is not None else [],
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


# ---------------------------------------------------------------------------
# Fallback strategy-section builder (moved from tools/build_itinerary.py)
# ---------------------------------------------------------------------------


def _build_strategy_sections(
    tiles_by_category: Dict[str, List[Dict[str, Any]]],
    constraints: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Build minimal strategy sections from tiles.

    This is a simplified fallback for when real strategy sections aren't
    available from the agent context (e.g., the architect node hasn't run
    or the tool is invoked standalone). The full graph populates
    strategy_sections via the architect node; this approximation groups
    tiles by specialist type and attaches matching constraints so the
    builder has enough structure to generate a day skeleton.

    The ItineraryBuilder expects strategy_sections (output of the architect
    node). When the tool is called outside the full graph, we synthesize
    lightweight sections from the tile categories so the builder has
    something to work with.
    """
    sections: List[Dict[str, Any]] = []

    # Group activity tiles by specialist_type or category
    activity_tiles = tiles_by_category.get("activities", [])
    specialist_groups: Dict[str, List[Dict[str, Any]]] = {}
    for tile in activity_tiles:
        meta = tile.get("meta") or {}
        specialist = meta.get("specialist_type") or meta.get("category") or "local_expert"
        specialist_groups.setdefault(specialist, []).append(tile)

    for specialist_type, tiles in specialist_groups.items():
        content_added: List[Dict[str, Any]] = []
        for tile in tiles:
            content_added.append(
                {
                    "type": "activity",
                    "title": tile.get("title", ""),
                    "description": tile.get("subtitle", ""),
                    "duration_hours": (tile.get("meta") or {}).get("duration_hours", 3.0),
                    "tile_id": tile.get("id"),
                }
            )

        # Attach constraints that match this specialist
        section_constraints: List[Dict[str, Any]] = []
        for c in constraints:
            applies_to = c.get("applies_to_categories", [])
            if not applies_to or specialist_type in applies_to:
                section_constraints.append(
                    {
                        "constraint_id": c.get("constraint_id", ""),
                        "type": c.get("type", ""),
                        "rule": c.get("rule", ""),
                        "severity": c.get("severity", "soft"),
                        "reason": c.get("reason", ""),
                    }
                )

        sections.append(
            {
                "specialist_type": specialist_type,
                "content_added": content_added,
                "constraints_applied": section_constraints,
            }
        )

    # If no activity tiles, add a placeholder local_expert section
    # so the builder still generates a day skeleton
    if not sections:
        sections.append(
            {
                "specialist_type": "local_expert",
                "content_added": [],
                "constraints_applied": [],
            }
        )

    return sections
