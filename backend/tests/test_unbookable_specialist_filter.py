"""
Tests for the no-bookable-specialist policy.

Policy: do NOT surface AI-suggested Tier-1 specialist activities that have no
bookable affiliate (Viator/GetYourGuide) product. Covers the shared predicate,
the in-build (expand-path) drop, the timing guardrail (no first-build nuking),
the non-target keep (general Google-Places tiles), the graph-path drop, and the
backfill of freed days.
"""

from __future__ import annotations

import pytest

from app.services.itinerary_builder import ItineraryBuilder, ItineraryBuilderInput
from app.services.partner_enrichment import (
    has_affiliate_booking,
    is_tier1_specialist_activity,
    is_unbookable_specialist_activity,
)

# A real Viator affiliate deeplink (used to stamp "bookable" tiles).
_VIATOR_DEEPLINK = "https://www.viator.com/tours/Bali/Sample/d22-12345?pid=P00012345"
# The placeholder/display-floor fallback: a bare Google-Maps search link.
_MAPS_DEEPLINK = "https://www.google.com/maps/search/Jemeluk%20Bay%20Coral%20Garden%20Dive%20Bali"


def _viator_tile(tile_id: str, title: str) -> dict:
    return {
        "id": tile_id,
        "type": "activity",
        "title": title,
        "provider": "viator",
        "partner": "viator",
        "partner_product_id": "P00012345",
        "deeplink": _VIATOR_DEEPLINK,
        "image_url": "https://media.viator.com/sample.jpg",
        "rating": 4.8,
        "review_count": 240,
        "is_estimate_only": False,
        "live_price": 89.0,
        "meta": {"specialist_type": "diving", "category": "diving"},
        "source_agent": "vertical_specialist",
    }


def _placeholder_specialist_tile(tile_id: str, title: str) -> dict:
    """Mirror of coordinator._specialist_content_to_tiles placeholder output."""
    return {
        "id": tile_id,
        "type": "activity",
        "title": title,
        "partner": "vertical_specialist",
        "partner_product_id": tile_id,
        "deeplink": _MAPS_DEEPLINK,
        "image_url": None,
        "rating": None,
        "is_estimate_only": True,
        "meta": {"specialist_type": "diving", "category": "diving"},
        "source_agent": "vertical_specialist",
    }


def _general_places_tile(tile_id: str, title: str) -> dict:
    """A real Google-Places general activity tile: real photo, no affiliate."""
    return {
        "id": tile_id,
        "type": "activity",
        "title": title,
        "image_url": "https://places.googleapis.com/photo/sample.jpg",
        "rating": 4.5,
        "review_count": 1200,
        "deeplink": "https://www.google.com/maps/place/?q=place_id:ChIJsample",
        "google_place_id": "ChIJsample",
        "geo": {"lat": -8.34, "lng": 115.5},
        "meta": {"category": "sightseeing"},
        "source_agent": "logistics_node",
    }


# =============================================================================
# Shared predicate
# =============================================================================


class TestSharedPredicate:
    def test_has_affiliate_booking_viator_tile(self):
        assert has_affiliate_booking(_viator_tile("t1", "Manta Point Dive")) is True

    def test_has_affiliate_booking_placeholder_tile_is_false(self):
        # Bare maps/search deeplink + vertical_specialist partner is NOT bookable.
        assert has_affiliate_booking(_placeholder_specialist_tile("t1", "Jemeluk Bay")) is False

    def test_has_affiliate_booking_maps_deeplink_only_is_false(self):
        assert has_affiliate_booking(None, _MAPS_DEEPLINK) is False

    def test_has_affiliate_booking_viator_deeplink_only_is_true(self):
        assert has_affiliate_booking(None, _VIATOR_DEEPLINK) is True

    def test_is_tier1_specialist_for_diving(self):
        assert (
            is_tier1_specialist_activity(
                specialist_type="diving",
                activity_domain=None,
                source_agent=None,
                provenance="ai_suggested",
            )
            is True
        )

    def test_browse_added_specialist_is_not_in_scope(self):
        # User-browse-added specialist content is explicitly out of policy scope.
        assert (
            is_tier1_specialist_activity(
                specialist_type="diving",
                activity_domain="tier1",
                source_agent="vertical_specialist",
                provenance="user_browse_added",
            )
            is False
        )

    def test_general_tile_is_not_tier1(self):
        assert (
            is_tier1_specialist_activity(
                specialist_type=None,
                activity_domain="tier2",
                source_agent="logistics_node",
                provenance="ai_suggested",
            )
            is False
        )

    def test_unbookable_specialist_drops_only_when_no_affiliate(self):
        # AI specialist + no affiliate -> drop.
        assert (
            is_unbookable_specialist_activity(
                specialist_type="diving",
                provenance="ai_suggested",
                matched_tile=_placeholder_specialist_tile("t1", "Jemeluk Bay"),
                deeplink=_MAPS_DEEPLINK,
            )
            is True
        )
        # AI specialist + viator affiliate -> keep.
        assert (
            is_unbookable_specialist_activity(
                specialist_type="diving",
                provenance="ai_suggested",
                matched_tile=_viator_tile("t2", "Manta Point Dive"),
                deeplink=_VIATOR_DEEPLINK,
            )
            is False
        )

    def test_general_tile_never_dropped_even_without_affiliate(self):
        assert (
            is_unbookable_specialist_activity(
                specialist_type=None,
                activity_domain="tier2",
                source_agent="logistics_node",
                provenance="ai_suggested",
                matched_tile=_general_places_tile("g1", "Tegallalang Rice Terraces"),
                deeplink="https://www.google.com/maps/place/?q=place_id:ChIJsample",
            )
            is False
        )


# =============================================================================
# In-build (expand path) drop + guardrail + backfill
# =============================================================================


def _build_sections(content: list[dict], specialist: str = "diving") -> list[dict]:
    return [
        {
            "specialist_type": specialist,
            "content_added": content,
            "constraints_applied": [],
        }
    ]


class TestInBuildDrop:
    def test_expand_drops_nonaffiliate_keeps_viator(self):
        """Mixed set: one viator dive + one Jemeluk-style maps-only dive.

        Affiliate evidence exists (the viator tile), so the non-affiliate dive is
        dropped while the bookable one is kept.
        """
        sections = _build_sections(
            [
                {"title": "Manta Point Dive", "tile_id": "spec_viator", "duration_hours": 3.0},
                {
                    "title": "Jemeluk Bay Coral Garden Dive",
                    "tile_id": "spec_maps",
                    "duration_hours": 3.0,
                },
            ]
        )
        tiles = {
            "spec_viator": _viator_tile("spec_viator", "Manta Point Dive"),
            "spec_maps": _placeholder_specialist_tile("spec_maps", "Jemeluk Bay Coral Garden Dive"),
        }
        builder = ItineraryBuilder()
        result = builder.build(
            ItineraryBuilderInput(
                start_date="2024-03-15",
                end_date="2024-03-22",
                strategy_sections=sections,
                tiles=tiles,
                destination="Bali",
            )
        )
        assert result.success
        titles = [b.summary for day in result.day_cards for b in day.blocks if not b.is_buffer]
        assert any("Manta Point" in t for t in titles)
        assert not any("Jemeluk" in t for t in titles)

    def test_guardrail_first_build_drops_nothing(self):
        """No specialist tile carries affiliate enrichment yet (all placeholders).

        This is the first-build graph scenario. No affiliate evidence -> NOTHING
        is dropped, proving first build is never nuked.
        """
        sections = _build_sections(
            [
                {
                    "title": "Jemeluk Bay Coral Garden Dive",
                    "tile_id": "spec_a",
                    "duration_hours": 3.0,
                },
                {"title": "USAT Liberty Wreck Dive", "tile_id": "spec_b", "duration_hours": 3.0},
            ]
        )
        tiles = {
            "spec_a": _placeholder_specialist_tile("spec_a", "Jemeluk Bay Coral Garden Dive"),
            "spec_b": _placeholder_specialist_tile("spec_b", "USAT Liberty Wreck Dive"),
        }
        builder = ItineraryBuilder()
        result = builder.build(
            ItineraryBuilderInput(
                start_date="2024-03-15",
                end_date="2024-03-22",
                strategy_sections=sections,
                tiles=tiles,
                destination="Bali",
            )
        )
        assert result.success
        titles = [b.summary for day in result.day_cards for b in day.blocks if not b.is_buffer]
        assert any("Jemeluk" in t for t in titles)
        assert any("USAT Liberty" in t for t in titles)

    def test_general_places_tile_kept(self):
        """A general Google-Places activity (real photo, no affiliate) is KEPT.

        Specialist set has affiliate evidence (the viator dive), so the gate is
        active — but the general tile is not specialist content and survives.
        """
        sections = [
            {
                "specialist_type": "diving",
                "content_added": [
                    {"title": "Manta Point Dive", "tile_id": "spec_viator", "duration_hours": 3.0},
                ],
                "constraints_applied": [],
            },
            {
                "specialist_type": "general",
                "content_added": [
                    {
                        "title": "Tegallalang Rice Terraces",
                        "tile_id": "gp_1",
                        "duration_hours": 2.0,
                    },
                ],
                "constraints_applied": [],
            },
        ]
        tiles = {
            "spec_viator": _viator_tile("spec_viator", "Manta Point Dive"),
            "gp_1": _general_places_tile("gp_1", "Tegallalang Rice Terraces"),
        }
        builder = ItineraryBuilder()
        result = builder.build(
            ItineraryBuilderInput(
                start_date="2024-03-15",
                end_date="2024-03-22",
                strategy_sections=sections,
                tiles=tiles,
                destination="Bali",
            )
        )
        assert result.success
        # The general section is skipped by Phase 2 extraction (general/local_expert
        # provide context, not bookable activities), so the tile reaches the timeline
        # only via the experience/backfill phases — but it must never be DROPPED by
        # the specialist filter. Assert the predicate-level guarantee directly.
        assert (
            is_unbookable_specialist_activity(
                specialist_type=None,
                activity_domain="tier2",
                source_agent="logistics_node",
                provenance="ai_suggested",
                matched_tile=tiles["gp_1"],
                deeplink=tiles["gp_1"]["deeplink"],
            )
            is False
        )

    def test_freed_day_backfilled_from_remaining_pool(self):
        """After dropping a non-affiliate dive, a freed day is backfilled.

        Provide experience-generator tiles in the pool so Phase 5.6 fills the day
        freed by the dropped specialist activity rather than leaving it empty.
        """
        sections = _build_sections(
            [
                {"title": "Manta Point Dive", "tile_id": "spec_viator", "duration_hours": 3.0},
                {
                    "title": "Jemeluk Bay Coral Garden Dive",
                    "tile_id": "spec_maps",
                    "duration_hours": 3.0,
                },
            ]
        )
        tiles = {
            "spec_viator": _viator_tile("spec_viator", "Manta Point Dive"),
            "spec_maps": _placeholder_specialist_tile("spec_maps", "Jemeluk Bay Coral Garden Dive"),
            "exp_1": {
                "id": "exp_1",
                "type": "activity",
                "title": "Ubud Cooking Class",
                "image_url": "https://places.googleapis.com/photo/cook.jpg",
                "rating": 4.7,
                "geo": {"lat": -8.51, "lng": 115.26},
                "meta": {"category": "cooking", "duration_hours": 2.0},
                "source_agent": "experience_generator",
            },
            "exp_2": {
                "id": "exp_2",
                "type": "activity",
                "title": "Tegenungan Waterfall Visit",
                "image_url": "https://places.googleapis.com/photo/fall.jpg",
                "rating": 4.4,
                "geo": {"lat": -8.57, "lng": 115.28},
                "meta": {"category": "sightseeing", "duration_hours": 1.5},
                "source_agent": "experience_generator",
            },
        }
        builder = ItineraryBuilder()
        result = builder.build(
            ItineraryBuilderInput(
                start_date="2024-03-15",
                end_date="2024-03-20",
                strategy_sections=sections,
                tiles=tiles,
                destination="Bali",
            )
        )
        assert result.success
        # No day should be a broken/empty placeholder: every day has at least one
        # block, and the dropped Jemeluk dive is gone.
        for day in result.day_cards:
            assert day.blocks, f"Day {day.day_number} is empty"
        all_titles = [
            b.summary
            for day in result.day_cards
            for b in day.blocks
            if not b.is_buffer and b.activity_type != "free_day"
        ]
        assert not any("Jemeluk" in t for t in all_titles)
        # Backfill placed at least one experience tile.
        assert any(("Cooking" in t) or ("Waterfall" in t) for t in all_titles)


# =============================================================================
# Graph-path drop (post-enrichment, day-card blocks)
# =============================================================================


def _make_state(blocks: list[dict]) -> dict:
    return {
        "trip_plan": {"destination": "Bali"},
        "tiles": {"activities": []},
        "day_cards": [
            {"day_number": 1, "label": "Arrival Day", "blocks": blocks[:1]},
            {"day_number": 2, "label": "Diving Day", "blocks": blocks[1:]},
        ],
    }


def _spec_block(summary: str, deeplink: str, booked_tile: dict | None) -> dict:
    return {
        "summary": summary,
        "activity_type": "activity",
        "specialist_type": "diving",
        "activity_domain": "tier1",
        "activity_provenance": "ai_suggested",
        "is_buffer": False,
        "deeplink": deeplink,
        "booked_tile": booked_tile,
    }


class TestGraphPathDrop:
    def _enable_partners(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "viator_enabled", True, raising=False)
        monkeypatch.setattr(settings, "viator_api_key", "viator-key", raising=False)
        monkeypatch.setattr(settings, "get_your_guide_enabled", False, raising=False)
        monkeypatch.setattr(settings, "get_your_guide_api_key", "", raising=False)

    def test_drops_nonaffiliate_keeps_viator(self, monkeypatch):
        from app.planner.services.agent_runner import _drop_unbookable_specialist_blocks

        self._enable_partners(monkeypatch)
        arrival = {
            "summary": "Arrive in Bali",
            "activity_type": "arrival",
            "is_buffer": True,
        }
        viator_block = _spec_block(
            "Manta Point Dive", _VIATOR_DEEPLINK, _viator_tile("spec_viator", "Manta Point Dive")
        )
        maps_block = _spec_block(
            "Jemeluk Bay Coral Garden Dive",
            _MAPS_DEEPLINK,
            _placeholder_specialist_tile("spec_maps", "Jemeluk Bay Coral Garden Dive"),
        )
        state = _make_state([arrival, viator_block, maps_block])
        _drop_unbookable_specialist_blocks(state)

        summaries = [b["summary"] for card in state["day_cards"] for b in card["blocks"]]
        assert "Manta Point Dive" in summaries
        assert "Jemeluk Bay Coral Garden Dive" not in summaries
        assert "Arrive in Bali" in summaries  # buffer untouched

    def test_no_evidence_drops_nothing(self, monkeypatch):
        from app.planner.services.agent_runner import _drop_unbookable_specialist_blocks

        self._enable_partners(monkeypatch)
        arrival = {
            "summary": "Arrive in Bali",
            "activity_type": "arrival",
            "is_buffer": True,
        }
        maps_a = _spec_block(
            "Jemeluk Bay Coral Garden Dive",
            _MAPS_DEEPLINK,
            _placeholder_specialist_tile("a", "Jemeluk Bay Coral Garden Dive"),
        )
        maps_b = _spec_block(
            "USAT Liberty Wreck Dive",
            _MAPS_DEEPLINK,
            _placeholder_specialist_tile("b", "USAT Liberty Wreck Dive"),
        )
        state = _make_state([arrival, maps_a, maps_b])
        _drop_unbookable_specialist_blocks(state)

        summaries = [b["summary"] for card in state["day_cards"] for b in card["blocks"]]
        # No affiliate evidence in the set -> nothing dropped.
        assert "Jemeluk Bay Coral Garden Dive" in summaries
        assert "USAT Liberty Wreck Dive" in summaries

    def test_partners_disabled_drops_nothing(self, monkeypatch):
        from app.config import settings
        from app.planner.services.agent_runner import _drop_unbookable_specialist_blocks

        monkeypatch.setattr(settings, "viator_enabled", False, raising=False)
        monkeypatch.setattr(settings, "viator_api_key", "", raising=False)
        monkeypatch.setattr(settings, "get_your_guide_enabled", False, raising=False)
        monkeypatch.setattr(settings, "get_your_guide_api_key", "", raising=False)

        arrival = {"summary": "Arrive in Bali", "activity_type": "arrival", "is_buffer": True}
        viator_block = _spec_block(
            "Manta Point Dive", _VIATOR_DEEPLINK, _viator_tile("v", "Manta Point Dive")
        )
        maps_block = _spec_block(
            "Jemeluk Bay Coral Garden Dive",
            _MAPS_DEEPLINK,
            _placeholder_specialist_tile("m", "Jemeluk Bay Coral Garden Dive"),
        )
        state = _make_state([arrival, viator_block, maps_block])
        _drop_unbookable_specialist_blocks(state)

        summaries = [b["summary"] for card in state["day_cards"] for b in card["blocks"]]
        # Partners disabled -> post-enrichment is not authoritative -> drop nothing.
        assert "Jemeluk Bay Coral Garden Dive" in summaries
        assert "Manta Point Dive" in summaries

    def test_user_browse_added_specialist_kept(self, monkeypatch):
        from app.planner.services.agent_runner import _drop_unbookable_specialist_blocks

        self._enable_partners(monkeypatch)
        arrival = {"summary": "Arrive in Bali", "activity_type": "arrival", "is_buffer": True}
        viator_block = _spec_block(
            "Manta Point Dive", _VIATOR_DEEPLINK, _viator_tile("v", "Manta Point Dive")
        )
        # A user-browse-added dive site with no affiliate must NOT be dropped.
        browse_block = {
            "summary": "My Pinned Dive Site",
            "activity_type": "activity",
            "specialist_type": "diving",
            "activity_domain": "tier1",
            "activity_provenance": "user_browse_added",
            "is_buffer": False,
            "deeplink": _MAPS_DEEPLINK,
            "booked_tile": _placeholder_specialist_tile("p", "My Pinned Dive Site"),
        }
        state = _make_state([arrival, viator_block, browse_block])
        _drop_unbookable_specialist_blocks(state)

        summaries = [b["summary"] for card in state["day_cards"] for b in card["blocks"]]
        assert "My Pinned Dive Site" in summaries
        assert "Manta Point Dive" in summaries

    def test_emptied_day_becomes_free_day_placeholder(self, monkeypatch):
        from app.planner.services.agent_runner import _drop_unbookable_specialist_blocks

        self._enable_partners(monkeypatch)
        viator_block = _spec_block(
            "Manta Point Dive", _VIATOR_DEEPLINK, _viator_tile("v", "Manta Point Dive")
        )
        maps_block = _spec_block(
            "Jemeluk Bay Coral Garden Dive",
            _MAPS_DEEPLINK,
            _placeholder_specialist_tile("m", "Jemeluk Bay Coral Garden Dive"),
        )
        # Day 1 keeps the viator dive (evidence); Day 2 holds ONLY the dropped dive.
        state = {
            "trip_plan": {"destination": "Bali"},
            "tiles": {"activities": []},
            "day_cards": [
                {"day_number": 1, "label": "Diving Day", "blocks": [viator_block]},
                {"day_number": 2, "label": "Diving Day", "blocks": [maps_block]},
            ],
        }
        _drop_unbookable_specialist_blocks(state)

        day2 = state["day_cards"][1]
        # The emptied day is not a broken blank card: it has a free_day placeholder.
        assert day2["blocks"], "emptied day left with no blocks"
        assert day2["blocks"][0]["activity_type"] == "free_day"
        assert day2["label"] == "Free Day"
        # The dropped dive is gone everywhere.
        summaries = [b["summary"] for card in state["day_cards"] for b in card["blocks"]]
        assert "Jemeluk Bay Coral Garden Dive" not in summaries
        assert "Manta Point Dive" in summaries


# =============================================================================
# Shared artifact prune (browse pool + map pins + ghost sections)
# =============================================================================


def _browse_added_specialist_tile(tile_id: str, title: str) -> dict:
    """A user-browse-added specialist tile (out of policy scope, never dropped)."""
    return {
        "id": tile_id,
        "type": "activity",
        "title": title,
        "partner": "vertical_specialist",
        "deeplink": _MAPS_DEEPLINK,
        "is_estimate_only": True,
        "meta": {"specialist_type": "diving", "category": "diving", "source": "browse_add"},
        "source": "browse_add",
        "source_agent": "vertical_specialist",
    }


def _section(specialist: str) -> dict:
    return {
        "id": f"sec_{specialist}",
        "specialist_type": specialist,
        "subtitle": "Bali, Indonesia",
        "content_added": [],
        "constraints_applied": [],
    }


class TestArtifactPrune:
    """Unit tests for prune_unbookable_specialist_artifacts (shape-agnostic helper)."""

    def test_browse_pool_drops_unbookable_keeps_bookable_and_general(self):
        from app.services.partner_enrichment import prune_unbookable_specialist_artifacts

        tiles = [
            _viator_tile("spec_viator", "Manta Point Dive"),
            _placeholder_specialist_tile("spec_maps", "Jemeluk Bay Coral Garden Dive"),
            _general_places_tile("gp_1", "Tegallalang Rice Terraces"),
        ]
        sections = [_section("diving")]
        day_cards = [
            {"day_number": 1, "blocks": [{"specialist_type": "diving", "is_buffer": False}]}
        ]
        kept_tiles, kept_sections, dropped_ids, dropped_topics = (
            prune_unbookable_specialist_artifacts(tiles, sections, day_cards)
        )
        kept_ids = {t["id"] for t in kept_tiles}
        assert "spec_viator" in kept_ids  # bookable specialist tile kept
        assert "gp_1" in kept_ids  # general Google-Places tile kept
        assert "spec_maps" not in kept_ids  # unbookable specialist tile dropped
        assert dropped_ids == {"spec_maps"}
        # diving still bookable (USAT-equivalent viator) -> section kept.
        assert dropped_topics == set()
        assert len(kept_sections) == 1

    def test_ghost_section_pruned_when_specialist_fully_unbookable(self):
        from app.services.partner_enrichment import prune_unbookable_specialist_artifacts

        # hiking is bookable (fires the gate); ALL diving tiles are unbookable.
        hiking_tile = _viator_tile("spec_hike", "Mount Batur Sunrise Trek")
        hiking_tile["meta"] = {"specialist_type": "hiking", "category": "hiking"}
        tiles = [
            hiking_tile,
            _placeholder_specialist_tile("dive_a", "Jemeluk Bay Coral Garden Dive"),
            _placeholder_specialist_tile("dive_b", "USAT Liberty Wreck Dive"),
        ]
        sections = [_section("hiking"), _section("diving")]
        # No diving blocks remain (the block drop already removed them).
        day_cards = [
            {"day_number": 1, "blocks": [{"specialist_type": "hiking", "is_buffer": False}]}
        ]
        kept_tiles, kept_sections, dropped_ids, dropped_topics = (
            prune_unbookable_specialist_artifacts(tiles, sections, day_cards)
        )
        kept_ids = {t["id"] for t in kept_tiles}
        assert kept_ids == {"spec_hike"}  # both dive tiles dropped
        assert dropped_ids == {"dive_a", "dive_b"}
        assert dropped_topics == {"diving"}  # ghost diving section pruned
        kept_section_types = {s["specialist_type"] for s in kept_sections}
        assert kept_section_types == {"hiking"}  # diving section gone, hiking kept

    def test_mixed_specialist_keeps_section_and_bookable_tile(self):
        """The literal screenshot case: diving = USAT bookable + Jemeluk unbookable."""
        from app.services.partner_enrichment import prune_unbookable_specialist_artifacts

        tiles = [
            _viator_tile("usat", "USAT Liberty Wreck Dive"),
            _placeholder_specialist_tile("jemeluk", "Jemeluk Bay Coral Garden Dive"),
        ]
        sections = [_section("diving")]
        day_cards = [
            {"day_number": 1, "blocks": [{"specialist_type": "diving", "is_buffer": False}]}
        ]
        kept_tiles, kept_sections, dropped_ids, dropped_topics = (
            prune_unbookable_specialist_artifacts(tiles, sections, day_cards)
        )
        kept_ids = {t["id"] for t in kept_tiles}
        assert kept_ids == {"usat"}  # bookable kept, unbookable dropped
        assert dropped_ids == {"jemeluk"}
        assert dropped_topics == set()  # diving still has a bookable tile -> section kept
        assert len(kept_sections) == 1

    def test_no_affiliate_evidence_prunes_nothing(self):
        from app.services.partner_enrichment import prune_unbookable_specialist_artifacts

        # All specialist tiles placeholder -> gate never fires.
        tiles = [
            _placeholder_specialist_tile("dive_a", "Jemeluk Bay Coral Garden Dive"),
            _placeholder_specialist_tile("dive_b", "USAT Liberty Wreck Dive"),
            _general_places_tile("gp_1", "Tegallalang Rice Terraces"),
        ]
        sections = [_section("diving")]
        day_cards = [
            {"day_number": 1, "blocks": [{"specialist_type": "diving", "is_buffer": False}]}
        ]
        kept_tiles, kept_sections, dropped_ids, dropped_topics = (
            prune_unbookable_specialist_artifacts(tiles, sections, day_cards)
        )
        assert dropped_ids == set()
        assert dropped_topics == set()
        assert len(kept_tiles) == 3  # untouched
        assert len(kept_sections) == 1  # untouched

    def test_zero_tile_section_preserved_when_another_specialist_fires_gate(self):
        """An infeasible / zero-activity specialist section is NOT a ghost.

        _inject_specialist_tiles_into_state skips infeasible sections, so an
        infeasible specialist legitimately has zero tiles + zero blocks. When a
        DIFFERENT bookable specialist fires the affiliate-evidence gate, that
        infeasible explanatory Advice card must survive (the section drop is tied
        to topics whose tiles THIS run actually dropped, not mere absence).
        """
        from app.services.partner_enrichment import prune_unbookable_specialist_artifacts

        hiking_tile = _viator_tile("spec_hike", "Mount Batur Sunrise Trek")
        hiking_tile["meta"] = {"specialist_type": "hiking", "category": "hiking"}
        tiles = [hiking_tile]  # diving produced NO tiles (infeasible) and was not dropped
        infeasible_diving = _section("diving")
        infeasible_diving["feasibility_status"] = "infeasible"
        sections = [_section("hiking"), infeasible_diving]
        day_cards = [
            {"day_number": 1, "blocks": [{"specialist_type": "hiking", "is_buffer": False}]}
        ]
        _kept_tiles, kept_sections, dropped_ids, dropped_topics = (
            prune_unbookable_specialist_artifacts(tiles, sections, day_cards)
        )
        assert dropped_ids == set()  # no tile to drop
        assert dropped_topics == set()  # diving section preserved (not a ghost)
        assert {s["specialist_type"] for s in kept_sections} == {"hiking", "diving"}

    def test_user_browse_added_specialist_tile_never_dropped(self):
        from app.services.partner_enrichment import prune_unbookable_specialist_artifacts

        tiles = [
            _viator_tile("usat", "USAT Liberty Wreck Dive"),
            _browse_added_specialist_tile("pinned", "My Pinned Dive Site"),
        ]
        sections = [_section("diving")]
        day_cards = [
            {"day_number": 1, "blocks": [{"specialist_type": "diving", "is_buffer": False}]}
        ]
        kept_tiles, _kept_sections, dropped_ids, dropped_topics = (
            prune_unbookable_specialist_artifacts(tiles, sections, day_cards)
        )
        kept_ids = {t["id"] for t in kept_tiles}
        assert "pinned" in kept_ids  # browse-added specialist tile is out of scope
        assert dropped_ids == set()
        assert dropped_topics == set()

    def test_helper_does_not_mutate_inputs(self):
        from app.services.partner_enrichment import prune_unbookable_specialist_artifacts

        tiles = [
            _viator_tile("usat", "USAT Liberty Wreck Dive"),
            _placeholder_specialist_tile("jemeluk", "Jemeluk Bay Coral Garden Dive"),
        ]
        sections = [_section("diving")]
        day_cards = [
            {"day_number": 1, "blocks": [{"specialist_type": "diving", "is_buffer": False}]}
        ]
        original_tile_ids = [t["id"] for t in tiles]
        original_section_count = len(sections)
        prune_unbookable_specialist_artifacts(tiles, sections, day_cards)
        # Original lists untouched (callers splice the returned kept lists).
        assert [t["id"] for t in tiles] == original_tile_ids
        assert len(sections) == original_section_count


class TestGraphPathArtifactWiring:
    """The graph-path block drop also reconciles tiles + sections in-state."""

    def _enable_partners(self, monkeypatch):
        from app.config import settings

        monkeypatch.setattr(settings, "viator_enabled", True, raising=False)
        monkeypatch.setattr(settings, "viator_api_key", "viator-key", raising=False)
        monkeypatch.setattr(settings, "get_your_guide_enabled", False, raising=False)
        monkeypatch.setattr(settings, "get_your_guide_api_key", "", raising=False)

    def test_state_prunes_ghost_section_and_tile_and_signals_replace(self, monkeypatch):
        from app.planner.services.agent_runner import _drop_unbookable_specialist_blocks

        self._enable_partners(monkeypatch)
        # hiking bookable + placed; diving fully unbookable (block + tiles).
        hiking_tile = _viator_tile("spec_hike", "Mount Batur Sunrise Trek")
        hiking_tile["meta"] = {"specialist_type": "hiking", "category": "hiking"}
        hiking_block = _spec_block("Mount Batur Sunrise Trek", _VIATOR_DEEPLINK, hiking_tile)
        hiking_block["specialist_type"] = "hiking"
        dive_block = _spec_block(
            "Jemeluk Bay Coral Garden Dive",
            _MAPS_DEEPLINK,
            _placeholder_specialist_tile("dive_a", "Jemeluk Bay Coral Garden Dive"),
        )
        state = {
            "trip_plan": {"destination": "Bali"},
            "tiles": {
                "activities": [
                    hiking_tile,
                    _placeholder_specialist_tile("dive_a", "Jemeluk Bay Coral Garden Dive"),
                ]
            },
            "strategy_sections": [_section("hiking"), _section("diving")],
            "day_cards": [
                {"day_number": 1, "label": "Arrival Day", "blocks": [hiking_block]},
                {"day_number": 2, "label": "Diving Day", "blocks": [dive_block]},
            ],
            "turn_meta": {},
        }
        _drop_unbookable_specialist_blocks(state)

        # Block drop removed the dive block.
        summaries = [b["summary"] for card in state["day_cards"] for b in card["blocks"]]
        assert "Jemeluk Bay Coral Garden Dive" not in summaries
        assert "Mount Batur Sunrise Trek" in summaries
        # Tile pool pruned (browse pool + map pins).
        tile_ids = {t["id"] for t in state["tiles"]["activities"]}
        assert "dive_a" not in tile_ids
        assert "spec_hike" in tile_ids
        # Ghost diving section pruned, hiking kept.
        section_types = {s["specialist_type"] for s in state["strategy_sections"]}
        assert section_types == {"hiking"}
        # Replace signaled so the additive frontend pool drops the pins.
        assert state["turn_meta"].get("tiles_replaced") is True

    def test_state_mixed_keeps_section_drops_only_unbookable_tile(self, monkeypatch):
        from app.planner.services.agent_runner import _drop_unbookable_specialist_blocks

        self._enable_partners(monkeypatch)
        usat_tile = _viator_tile("usat", "USAT Liberty Wreck Dive")
        usat_block = _spec_block("USAT Liberty Wreck Dive", _VIATOR_DEEPLINK, usat_tile)
        jemeluk_block = _spec_block(
            "Jemeluk Bay Coral Garden Dive",
            _MAPS_DEEPLINK,
            _placeholder_specialist_tile("jemeluk", "Jemeluk Bay Coral Garden Dive"),
        )
        state = {
            "trip_plan": {"destination": "Bali"},
            "tiles": {
                "activities": [
                    usat_tile,
                    _placeholder_specialist_tile("jemeluk", "Jemeluk Bay Coral Garden Dive"),
                ]
            },
            "strategy_sections": [_section("diving")],
            "day_cards": [
                {"day_number": 1, "label": "Diving Day", "blocks": [usat_block, jemeluk_block]},
            ],
            "turn_meta": {},
        }
        _drop_unbookable_specialist_blocks(state)

        tile_ids = {t["id"] for t in state["tiles"]["activities"]}
        assert tile_ids == {"usat"}  # only unbookable tile dropped
        # diving section kept (still has a bookable tile + block).
        assert {s["specialist_type"] for s in state["strategy_sections"]} == {"diving"}


class TestExpandPathArtifactWiring:
    """Endpoint-shape: flat tiles_data dict + strategy_sections_data list.

    Mirrors the streaming.generate_ndjson splice (extract activity tiles from the
    flat id->tile dict, pop the dropped ids, force tiles_refreshed, swap sections).
    """

    def test_flat_dict_extraction_and_splice(self):
        from app.services.partner_enrichment import prune_unbookable_specialist_artifacts

        # Flat tiles_data: bookable hiking + unbookable diving + general place + a hotel.
        hiking_tile = _viator_tile("spec_hike", "Mount Batur Sunrise Trek")
        hiking_tile["meta"] = {"specialist_type": "hiking", "category": "hiking"}
        tiles_data = {
            "spec_hike": hiking_tile,
            "dive_a": _placeholder_specialist_tile("dive_a", "Jemeluk Bay Coral Garden Dive"),
            "gp_1": _general_places_tile("gp_1", "Tegallalang Rice Terraces"),
            "hotel_1": {"id": "hotel_1", "type": "hotel", "title": "Hotel Bali"},
        }
        strategy_sections_data = [_section("hiking"), _section("diving")]
        expand_day_cards = [
            {"day_number": 1, "blocks": [{"specialist_type": "hiking", "is_buffer": False}]}
        ]

        # --- endpoint splice logic (copy of streaming.generate_ndjson) ---
        activity_ids = [
            tid
            for tid, t in tiles_data.items()
            if isinstance(t, dict) and t.get("type", "activity") == "activity"
        ]
        activity_tiles = [tiles_data[tid] for tid in activity_ids]
        _kept, kept_sections, dropped_ids, dropped_topics = prune_unbookable_specialist_artifacts(
            activity_tiles, strategy_sections_data, expand_day_cards
        )
        tiles_refreshed = False
        if dropped_ids:
            for tid in dropped_ids:
                tiles_data.pop(tid, None)
            tiles_refreshed = True
        if dropped_topics:
            strategy_sections_data = kept_sections
        # --- assertions on what the endpoint would persist/emit ---
        assert tiles_refreshed is True  # forces emit/persist of shrunk pool
        assert "dive_a" not in tiles_data  # unbookable specialist tile gone
        assert "spec_hike" in tiles_data  # bookable specialist kept
        assert "gp_1" in tiles_data  # general place kept
        assert "hotel_1" in tiles_data  # hotel never touched
        assert {s["specialist_type"] for s in strategy_sections_data} == {"hiking"}
        assert dropped_topics == {"diving"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
