# backend/tests/test_section_builder.py
"""
Unit tests for section_builder.py — pure logic, zero project imports inside the module.

Tests cover all 5 public functions:
- sort_sections_anchor_first: anchor ordering invariant
- upsert_section: CRUD + dedup + anchor sort
- mark_topic_executed: dedup append + copy-before-mutate
- build_specialist_section: correct dict shape
- build_local_expert_section: correct dict shape
"""

from __future__ import annotations

from app.planner.services.section_builder import (
    build_local_expert_section,
    build_specialist_section,
    mark_topic_executed,
    sort_sections_anchor_first,
    upsert_section,
)

# =============================================================================
# sort_sections_anchor_first
# =============================================================================


class TestSortSectionsAnchorFirst:
    """Anchor types (local_expert, general) must always appear at index 0."""

    def test_anchor_local_expert_moves_to_front(self) -> None:
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "local_expert"},
        ]
        result = sort_sections_anchor_first(sections)
        assert result[0]["specialist_type"] == "local_expert"
        assert result[1]["specialist_type"] == "diving"

    def test_anchor_general_moves_to_front(self) -> None:
        sections = [
            {"specialist_type": "hiking"},
            {"specialist_type": "general"},
        ]
        result = sort_sections_anchor_first(sections)
        assert result[0]["specialist_type"] == "general"
        assert result[1]["specialist_type"] == "hiking"

    def test_mixed_order_with_multiple_specialists(self) -> None:
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "hiking"},
            {"specialist_type": "local_expert"},
            {"specialist_type": "skiing"},
        ]
        result = sort_sections_anchor_first(sections)
        assert result[0]["specialist_type"] == "local_expert"
        # Non-anchors preserve relative order
        non_anchor_types = [s["specialist_type"] for s in result[1:]]
        assert non_anchor_types == ["diving", "hiking", "skiing"]

    def test_empty_list(self) -> None:
        assert sort_sections_anchor_first([]) == []

    def test_all_anchors(self) -> None:
        sections = [
            {"specialist_type": "general"},
            {"specialist_type": "local_expert"},
        ]
        result = sort_sections_anchor_first(sections)
        # Both are anchors, should both stay at front in original order
        assert len(result) == 2
        types = [s["specialist_type"] for s in result]
        assert set(types) == {"general", "local_expert"}

    def test_no_anchors(self) -> None:
        sections = [
            {"specialist_type": "diving"},
            {"specialist_type": "skiing"},
        ]
        result = sort_sections_anchor_first(sections)
        # Order preserved
        assert [s["specialist_type"] for s in result] == ["diving", "skiing"]

    def test_missing_specialist_type_key(self) -> None:
        sections = [
            {"id": "orphan"},
            {"specialist_type": "local_expert"},
        ]
        result = sort_sections_anchor_first(sections)
        assert result[0]["specialist_type"] == "local_expert"
        assert result[1] == {"id": "orphan"}


# =============================================================================
# upsert_section
# =============================================================================


class TestUpsertSection:
    """Upsert creates, deduplicates, and sorts strategy_sections in metadata."""

    def test_creates_strategy_sections_if_missing(self) -> None:
        metadata: dict = {}
        section = {"specialist_type": "diving", "id": "specialist_diving"}
        upsert_section(metadata, section)
        assert "strategy_sections" in metadata
        assert len(metadata["strategy_sections"]) == 1
        assert metadata["strategy_sections"][0]["specialist_type"] == "diving"

    def test_deduplicates_by_specialist_type(self) -> None:
        metadata: dict = {
            "strategy_sections": [
                {"specialist_type": "diving", "version": 1},
            ]
        }
        upsert_section(metadata, {"specialist_type": "diving", "version": 2})
        assert len(metadata["strategy_sections"]) == 1
        assert metadata["strategy_sections"][0]["version"] == 2

    def test_appendable_mode_appends(self) -> None:
        metadata: dict = {
            "strategy_sections": [
                {"specialist_type": "local_expert", "id": "le"},
            ]
        }
        upsert_section(metadata, {"specialist_type": "diving", "id": "div"}, mode="appendable")
        assert len(metadata["strategy_sections"]) == 2
        # Anchor stays at front after sort
        assert metadata["strategy_sections"][0]["specialist_type"] == "local_expert"
        assert metadata["strategy_sections"][1]["specialist_type"] == "diving"

    def test_singleton_mode_inserts_at_index_0(self) -> None:
        metadata: dict = {
            "strategy_sections": [
                {"specialist_type": "diving", "id": "div"},
            ]
        }
        upsert_section(
            metadata,
            {"specialist_type": "general", "id": "gen"},
            mode="singleton",
        )
        # general is an anchor, should be at index 0 after sort
        assert metadata["strategy_sections"][0]["specialist_type"] == "general"

    def test_anchor_sort_applied_after_upsert(self) -> None:
        metadata: dict = {
            "strategy_sections": [
                {"specialist_type": "diving", "id": "div"},
            ]
        }
        upsert_section(metadata, {"specialist_type": "local_expert", "id": "le"})
        # Anchor should be at position 0
        assert metadata["strategy_sections"][0]["specialist_type"] == "local_expert"

    def test_idempotent_same_type_twice(self) -> None:
        metadata: dict = {"strategy_sections": []}
        section = {"specialist_type": "hiking", "content": "v1"}
        upsert_section(metadata, section)
        upsert_section(metadata, {"specialist_type": "hiking", "content": "v2"})
        assert len(metadata["strategy_sections"]) == 1
        assert metadata["strategy_sections"][0]["content"] == "v2"

    def test_multiple_different_types(self) -> None:
        metadata: dict = {"strategy_sections": []}
        upsert_section(metadata, {"specialist_type": "diving"})
        upsert_section(metadata, {"specialist_type": "hiking"})
        upsert_section(metadata, {"specialist_type": "skiing"})
        assert len(metadata["strategy_sections"]) == 3


# =============================================================================
# mark_topic_executed
# =============================================================================


class TestMarkTopicExecuted:
    """Deduplicating append to executed_strategy_topics with copy-before-mutate."""

    def test_creates_key_if_missing(self) -> None:
        metadata: dict = {}
        mark_topic_executed(metadata, "diving")
        assert metadata["executed_strategy_topics"] == ["diving"]

    def test_appends_new_topic(self) -> None:
        metadata: dict = {"executed_strategy_topics": ["diving"]}
        mark_topic_executed(metadata, "hiking")
        assert "hiking" in metadata["executed_strategy_topics"]
        assert "diving" in metadata["executed_strategy_topics"]

    def test_deduplicates_same_topic(self) -> None:
        metadata: dict = {"executed_strategy_topics": ["diving"]}
        mark_topic_executed(metadata, "diving")
        assert metadata["executed_strategy_topics"].count("diving") == 1

    def test_does_not_mutate_original_list_reference(self) -> None:
        original_list = ["diving"]
        metadata: dict = {"executed_strategy_topics": original_list}
        mark_topic_executed(metadata, "hiking")
        # The function should copy before mutate, so original list is unchanged
        assert original_list == ["diving"]
        # But metadata has the new list
        assert metadata["executed_strategy_topics"] == ["diving", "hiking"]

    def test_already_existing_topic_does_not_copy(self) -> None:
        """When topic already exists, no mutation occurs at all."""
        original_list = ["diving"]
        metadata: dict = {"executed_strategy_topics": original_list}
        mark_topic_executed(metadata, "diving")
        # No new list created since no append happened
        assert metadata["executed_strategy_topics"] is original_list

    def test_multiple_topics(self) -> None:
        metadata: dict = {}
        mark_topic_executed(metadata, "diving")
        mark_topic_executed(metadata, "hiking")
        mark_topic_executed(metadata, "skiing")
        assert metadata["executed_strategy_topics"] == ["diving", "hiking", "skiing"]


# =============================================================================
# build_specialist_section
# =============================================================================


class TestBuildSpecialistSection:
    """build_specialist_section returns a well-shaped dict with all required keys."""

    def test_returns_correct_shape(self) -> None:
        section = build_specialist_section(
            topic="diving",
            destination="Bali",
            start_date="2026-03-01",
            end_date="2026-03-07",
            feasibility_status="feasible",
            feasibility_reason=None,
            alternative_suggestion=None,
            constraints=[{"rule": "no_fly_24h"}],
            content_added=[{"type": "activity", "title": "Reef Dive"}],
            enhancements=["Night dive", "Wreck dive", "Manta dive", "Cave dive"],
            hero_image="https://example.com/dive.jpg",
            day_pref=3,
        )

        assert section["id"] == "specialist_diving"
        assert section["title"] == "Diving Specialist"
        assert section["specialist_type"] == "diving"
        assert section["subtitle"] == "Bali"
        assert section["_cache_dates"] == "2026-03-01:2026-03-07"
        assert section["_cache_day_pref"] == 3
        assert section["feasibility_status"] == "feasible"
        assert section["constraints_applied"] == [{"rule": "no_fly_24h"}]
        assert section["content_added"] == [{"type": "activity", "title": "Reef Dive"}]
        assert section["content_blocks"] == section["content_added"]
        assert section["hero_image"] == "https://example.com/dive.jpg"
        assert section["impact_areas"] == ["Diving", "Safety", "Activities"]
        # Enhancements capped at 3
        assert section["optional_upgrades"] == ["Night dive", "Wreck dive", "Manta dive"]
        # Required empty fields
        assert section["principles"] == []
        assert section["must_dos"] == []
        assert section["logistics_notes"] == []
        assert section["bullets"] == []

    def test_empty_enhancements(self) -> None:
        section = build_specialist_section(
            topic="hiking",
            destination="Nepal",
            start_date=None,
            end_date=None,
            feasibility_status="caveat",
            feasibility_reason="Monsoon season",
            alternative_suggestion="Visit in October",
            constraints=[],
            content_added=[],
            enhancements=[],
            hero_image=None,
        )
        assert section["optional_upgrades"] == []
        assert section["feasibility_reason"] == "Monsoon season"
        assert section["alternative_suggestion"] == "Visit in October"

    def test_day_pref_defaults_to_none(self) -> None:
        section = build_specialist_section(
            topic="skiing",
            destination="Chamonix",
            start_date="2026-01-15",
            end_date="2026-01-20",
            feasibility_status="feasible",
            feasibility_reason=None,
            alternative_suggestion=None,
            constraints=[],
            content_added=[],
            enhancements=[],
            hero_image=None,
        )
        assert section["_cache_day_pref"] is None


# =============================================================================
# build_local_expert_section
# =============================================================================


class TestBuildLocalExpertSection:
    """build_local_expert_section returns a well-shaped dict for the anchor section."""

    def test_returns_correct_shape(self) -> None:
        section = build_local_expert_section(
            destination="Tokyo",
            one_liner="A vibrant mix of tradition and modernity.",
            bullets=["Cherry blossoms in March", "Tsukiji fish market"],
            must_dos=["Visit Meiji Shrine", "Try ramen in Shinjuku"],
            logistics_notes=["JR Pass recommended", "Cash is king outside Tokyo"],
            constraints_applied=[],
            content_added=[{"type": "tip", "title": "Local etiquette"}],
            gallery_images=[{"url": "https://example.com/tokyo.jpg", "alt": "Tokyo skyline"}],
            travel_intelligence={"safety": "very safe", "visa": "visa-free for most"},
        )

        assert section["id"] == "strategy_local_expert"
        assert section["specialist_type"] == "local_expert"
        assert section["title"] == "Tokyo Trip Overview"
        assert section["one_liner"] == "A vibrant mix of tradition and modernity."
        assert section["bullets"] == ["Cherry blossoms in March", "Tsukiji fish market"]
        assert section["must_dos"] == ["Visit Meiji Shrine", "Try ramen in Shinjuku"]
        assert section["logistics_notes"] == ["JR Pass recommended", "Cash is king outside Tokyo"]
        assert section["constraints_applied"] == []
        assert section["content_added"] == [{"type": "tip", "title": "Local etiquette"}]
        assert section["content_blocks"] == section["content_added"]
        assert section["impact_areas"] == ["Logistics", "Timing", "Culture"]
        assert len(section["destination_gallery"]) == 1
        assert section["travel_intelligence"]["safety"] == "very safe"
        assert section["principles"] == []
        assert section["optional_upgrades"] == []

    def test_specialist_type_is_local_expert(self) -> None:
        section = build_local_expert_section(
            destination="Paris",
            one_liner="City of lights.",
            bullets=[],
            must_dos=[],
            logistics_notes=[],
            constraints_applied=[],
            content_added=[],
            gallery_images=[],
            travel_intelligence={},
        )
        assert section["specialist_type"] == "local_expert"
