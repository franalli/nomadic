"""Tests for post-arrangement constraint recomputation.

Covers recompute_constraints_after_arrangement() which runs after
apply-arrangement to fix stale constraint tags and detect orphaned buffers.
"""

import time

from app.services.itinerary_builder import (
    _detect_stale_buffers,
    _recompute_nofly_tags,
    recompute_constraints_after_arrangement,
)

# ── Helpers ──────────────────────────────────────────────────────────────────


def _block(
    block_id: str,
    specialist_type: str = "",
    activity_type: str = "activity",
    is_buffer: bool = False,
    buffer_type: str | None = None,
    active_constraints: list | None = None,
    intensity: str | None = None,
    period: str = "morning",
    summary: str = "",
    constraints: list | None = None,
) -> dict:
    """Build a minimal block dict for testing."""
    b: dict = {
        "id": block_id,
        "specialist_type": specialist_type,
        "activity_type": activity_type,
        "is_buffer": is_buffer,
        "period": period,
        "summary": summary or f"{specialist_type} {activity_type}",
    }
    if buffer_type is not None:
        b["buffer_type"] = buffer_type
    if active_constraints is not None:
        b["active_constraints"] = active_constraints
    if intensity is not None:
        b["intensity"] = intensity
    if constraints is not None:
        b["constraints"] = constraints
    return b


def _day(day_number: int, blocks: list[dict]) -> dict:
    return {"day_number": day_number, "blocks": blocks, "label": f"Day {day_number}"}


def _tag(tag_id: str, severity: str = "info") -> dict:
    return {"id": tag_id, "severity": severity, "icon": "", "title": "", "description": ""}


# ── Pass 1: nofly tag recomputation ─────────────────────────────────────────


class TestRecomputeNoflyTags:
    def test_nofly_tag_stripped_when_dive_moved_away_from_departure(self):
        """Dive on day 5 of 6 has no_fly_buffer. After moving to day 2,
        tag should be stripped (not near departure anymore)."""
        cards = [
            _day(
                1,
                [
                    _block(
                        "arr",
                        activity_type="arrival",
                        is_buffer=True,
                        buffer_type="arrival",
                    )
                ],
            ),
            _day(
                2,
                [
                    _block(
                        "dive1",
                        "diving",
                        active_constraints=[
                            _tag("no_fly_buffer", "warning"),
                            _tag("surface_interval"),
                        ],
                    )
                ],
            ),
            _day(3, []),
            _day(4, []),
            _day(5, []),
            _day(
                6,
                [
                    _block(
                        "dep",
                        activity_type="departure",
                        is_buffer=True,
                        buffer_type="departure",
                    )
                ],
            ),
        ]

        result = _recompute_nofly_tags(cards)
        dive_block = result[1]["blocks"][0]
        tag_ids = {c["id"] for c in dive_block["active_constraints"]}

        # surface_interval is intrinsic → kept
        assert "surface_interval" in tag_ids
        # no_fly_buffer is position-dependent → stripped (day 2 is not within 2 of day 6)
        assert "no_fly_buffer" not in tag_ids

    def test_nofly_tag_added_when_dive_moved_near_departure(self):
        """Dive on day 2 has only surface_interval. After conceptually
        being the last dive on day 5 of 6, should gain no_fly_buffer."""
        cards = [
            _day(1, []),
            _day(2, []),
            _day(3, []),
            _day(4, []),
            _day(
                5,
                [
                    _block(
                        "dive1",
                        "diving",
                        active_constraints=[
                            _tag("surface_interval"),
                        ],
                    )
                ],
            ),
            _day(
                6,
                [
                    _block(
                        "dep",
                        activity_type="departure",
                        is_buffer=True,
                        buffer_type="departure",
                    )
                ],
            ),
        ]

        result = _recompute_nofly_tags(cards)
        dive_block = result[4]["blocks"][0]
        tag_ids = {c["id"] for c in dive_block["active_constraints"]}

        # Now within 2 days of departure (day 5, departure day 6)
        assert "no_fly_buffer" in tag_ids
        # surface_interval is intrinsic → still kept
        assert "surface_interval" in tag_ids

    def test_surface_interval_survives_any_move(self):
        """surface_interval is intrinsic — never stripped regardless of position."""
        cards = [
            _day(
                1,
                [
                    _block(
                        "dive1",
                        "diving",
                        active_constraints=[
                            _tag("surface_interval"),
                        ],
                    )
                ],
            ),
            _day(2, []),
            _day(3, []),
            _day(4, []),
            _day(5, []),
            _day(6, []),
            _day(7, []),
            _day(8, []),
        ]

        result = _recompute_nofly_tags(cards)
        dive_block = result[0]["blocks"][0]
        tag_ids = {c["id"] for c in dive_block["active_constraints"]}

        assert "surface_interval" in tag_ids

    def test_surface_interval_fallback_when_nofly_stripped(self):
        """Block with ONLY no_fly_buffer (realistic builder output near departure)
        gets surface_interval added back when moved away from departure."""
        cards = [
            _day(
                1,
                [
                    _block(
                        "dive1",
                        "diving",
                        active_constraints=[
                            _tag("no_fly_buffer", "warning"),
                        ],
                    )
                ],
            ),
            _day(2, []),
            _day(3, []),
            _day(4, []),
            _day(5, []),
            _day(6, []),
        ]

        result = _recompute_nofly_tags(cards)
        dive_block = result[0]["blocks"][0]
        tag_ids = {c["id"] for c in dive_block["active_constraints"]}

        # no_fly_buffer stripped (day 1 is far from departure day 6)
        assert "no_fly_buffer" not in tag_ids
        # surface_interval added as fallback — block must not lose all tags
        assert "surface_interval" in tag_ids

    def test_intrinsic_tags_preserved_through_recomputation(self):
        """Tags like fitness_required, altitude_buffer, tide_timing survive."""
        cards = [
            _day(
                1,
                [
                    _block(
                        "hike1",
                        "hiking",
                        active_constraints=[
                            _tag("fitness_required"),
                            _tag("altitude_buffer"),
                            _tag("early_start_recommended"),
                        ],
                    )
                ],
            ),
            _day(
                2,
                [
                    _block(
                        "surf1",
                        "surfing",
                        active_constraints=[
                            _tag("tide_timing"),
                        ],
                    )
                ],
            ),
            _day(
                3,
                [
                    _block(
                        "ski1",
                        "skiing",
                        active_constraints=[
                            _tag("advanced_terrain"),
                            _tag("avalanche_awareness", "warning"),
                        ],
                    )
                ],
            ),
        ]

        result = _recompute_nofly_tags(cards)

        hike_tags = {c["id"] for c in result[0]["blocks"][0]["active_constraints"]}
        assert hike_tags == {"fitness_required", "altitude_buffer", "early_start_recommended"}

        surf_tags = {c["id"] for c in result[1]["blocks"][0]["active_constraints"]}
        assert surf_tags == {"tide_timing"}

        ski_tags = {c["id"] for c in result[2]["blocks"][0]["active_constraints"]}
        assert ski_tags == {"advanced_terrain", "avalanche_awareness"}

    def test_multiple_dive_blocks_only_last_gets_nofly(self):
        """With dives on days 3 and 5 (of 6), only day 5 gets no_fly_buffer."""
        cards = [
            _day(1, []),
            _day(2, []),
            _day(3, [_block("dive1", "diving", active_constraints=[_tag("surface_interval")])]),
            _day(4, []),
            _day(5, [_block("dive2", "diving", active_constraints=[_tag("surface_interval")])]),
            _day(6, []),
        ]

        result = _recompute_nofly_tags(cards)
        dive1_tags = {c["id"] for c in result[2]["blocks"][0]["active_constraints"]}
        dive2_tags = {c["id"] for c in result[4]["blocks"][0]["active_constraints"]}

        assert "no_fly_buffer" not in dive1_tags
        assert "surface_interval" in dive1_tags
        assert "no_fly_buffer" in dive2_tags
        assert "surface_interval" in dive2_tags

    def test_buffer_blocks_are_skipped(self):
        """Buffer blocks (is_buffer=True) are never tagged."""
        cards = [
            _day(1, [_block("buf1", "diving", is_buffer=True, buffer_type="rest_day")]),
            _day(2, []),
        ]

        result = _recompute_nofly_tags(cards)
        # Buffer block should not have had active_constraints set
        buf = result[0]["blocks"][0]
        assert "active_constraints" not in buf or buf.get("active_constraints") is None


# ── Pass 2: stale buffer detection ──────────────────────────────────────────


class TestDetectStaleBuffers:
    def test_orphaned_rest_day_detected(self):
        """Rest day buffer on day 4 between dive (day 3) and hike (day 5).
        Hike moved to day 2 → buffer on day 4 is orphaned."""
        cards = [
            _day(1, []),
            _day(2, [_block("hike1", "hiking")]),
            _day(3, [_block("dive1", "diving")]),
            _day(
                4,
                [
                    _block(
                        "buf1",
                        is_buffer=True,
                        buffer_type="rest_day",
                        summary="No high-altitude within 24h",
                        constraints=["no_altitude_after_dive"],
                    )
                ],
            ),
            _day(5, []),
        ]

        updated, violations = _detect_stale_buffers(cards)

        assert len(violations) == 1
        assert violations[0]["violation_code"] == "ORPHANED_BUFFER"
        assert violations[0]["target_day"] == 4

        # Buffer block mutated
        buf = updated[3]["blocks"][0]
        assert "no longer required" in buf["summary"]
        assert buf["constraints"] == []

    def test_missing_cross_domain_buffer_detected(self):
        """Dive on day 3, hike on day 4, no rest buffer between → detected."""
        cards = [
            _day(1, []),
            _day(2, []),
            _day(3, [_block("dive1", "diving")]),
            _day(4, [_block("hike1", "hiking")]),
            _day(5, []),
        ]

        _, violations = _detect_stale_buffers(cards)

        missing = [v for v in violations if v["violation_code"] == "MISSING_CROSS_DOMAIN_BUFFER"]
        assert len(missing) == 1
        assert missing[0]["target_day"] == 4

    def test_no_false_positive_same_domain(self):
        """Moving dives around within same domain → no buffer violations."""
        cards = [
            _day(1, [_block("dive1", "diving")]),
            _day(2, [_block("dive2", "diving")]),
            _day(3, [_block("dive3", "diving")]),
        ]

        _, violations = _detect_stale_buffers(cards)
        assert len(violations) == 0

    def test_valid_buffer_not_flagged(self):
        """Dive on 2, rest on 3, hike on 4 → buffer is valid, no violation."""
        cards = [
            _day(1, []),
            _day(2, [_block("dive1", "diving")]),
            _day(3, [_block("buf1", is_buffer=True, buffer_type="rest_day", summary="Rest day")]),
            _day(4, [_block("hike1", "hiking")]),
            _day(5, []),
        ]

        _, violations = _detect_stale_buffers(cards)
        assert len(violations) == 0

    def test_orphaned_acclimatization_detected(self):
        """Acclimatization on day 2, but all hiking moved to day 6+."""
        cards = [
            _day(1, []),
            _day(
                2,
                [
                    _block(
                        "accl1",
                        is_buffer=True,
                        buffer_type="acclimatization",
                        summary="Max 500m elevation gain",
                        constraints=["altitude_acclimatization"],
                    )
                ],
            ),
            _day(3, []),
            _day(4, []),
            _day(5, []),
            _day(6, [_block("hike1", "hiking")]),
        ]

        updated, violations = _detect_stale_buffers(cards)

        orphaned = [v for v in violations if v["violation_code"] == "ORPHANED_BUFFER"]
        assert len(orphaned) == 1
        assert orphaned[0]["target_day"] == 2

        buf = updated[1]["blocks"][0]
        assert "no longer required" in buf["summary"]
        assert buf["constraints"] == []

    def test_acclimatization_valid_when_altitude_soon(self):
        """Acclimatization on day 2, hiking on day 3 → no violation."""
        cards = [
            _day(1, []),
            _day(
                2,
                [
                    _block(
                        "accl1",
                        is_buffer=True,
                        buffer_type="acclimatization",
                        summary="Max 500m elevation",
                    )
                ],
            ),
            _day(3, [_block("hike1", "hiking")]),
        ]

        _, violations = _detect_stale_buffers(cards)
        assert len(violations) == 0

    def test_missing_buffer_with_gap_of_2(self):
        """Dive on day 2, hike on day 4 (gap of 2), no buffer → detected."""
        cards = [
            _day(1, []),
            _day(2, [_block("dive1", "diving")]),
            _day(3, []),
            _day(4, [_block("hike1", "hiking")]),
            _day(5, []),
        ]

        _, violations = _detect_stale_buffers(cards)

        missing = [v for v in violations if v["violation_code"] == "MISSING_CROSS_DOMAIN_BUFFER"]
        assert len(missing) == 1

    def test_no_missing_buffer_with_gap_of_3(self):
        """Dive on day 2, hike on day 5 (gap of 3) → no violation (>2 gap)."""
        cards = [
            _day(1, []),
            _day(2, [_block("dive1", "diving")]),
            _day(3, []),
            _day(4, []),
            _day(5, [_block("hike1", "hiking")]),
        ]

        _, violations = _detect_stale_buffers(cards)

        missing = [v for v in violations if v["violation_code"] == "MISSING_CROSS_DOMAIN_BUFFER"]
        assert len(missing) == 0


# ── Integration: full recompute_constraints_after_arrangement ────────────────


class TestRecomputeConstraintsAfterArrangement:
    def test_end_to_end_dive_moved_and_buffer_orphaned(self):
        """Full pipeline: dive moved away from departure + buffer orphaned."""
        cards = [
            _day(
                1,
                [
                    _block(
                        "dive1",
                        "diving",
                        active_constraints=[
                            _tag("no_fly_buffer", "warning"),
                            _tag("surface_interval"),
                        ],
                    )
                ],
            ),
            _day(2, []),
            _day(
                3,
                [
                    _block(
                        "buf1",
                        is_buffer=True,
                        buffer_type="rest_day",
                        summary="Rest between phases",
                        constraints=["no_altitude_after_dive"],
                    )
                ],
            ),
            _day(4, []),
            _day(5, []),
            _day(6, []),
        ]

        updated, violations = recompute_constraints_after_arrangement(cards, None)

        # no_fly_buffer stripped (day 1 is far from departure day 6)
        dive = updated[0]["blocks"][0]
        tag_ids = {c["id"] for c in dive["active_constraints"]}
        assert "no_fly_buffer" not in tag_ids
        assert "surface_interval" in tag_ids

        # Buffer orphaned (no altitude after it)
        assert any(v["violation_code"] == "ORPHANED_BUFFER" for v in violations)
        buf = updated[2]["blocks"][0]
        assert "no longer required" in buf["summary"]

    def test_performance_10_day_trip(self):
        """10-day trip with 20 blocks completes in <50ms."""
        cards = []
        for d in range(1, 11):
            blocks = [
                _block(
                    f"b{d}_1",
                    "diving" if d <= 3 else "hiking",
                    active_constraints=[_tag("surface_interval")] if d <= 3 else [],
                ),
                _block(f"b{d}_2", "diving" if d <= 3 else "hiking"),
            ]
            cards.append(_day(d, blocks))

        start = time.monotonic()
        recompute_constraints_after_arrangement(cards, None)
        elapsed_ms = (time.monotonic() - start) * 1000

        assert elapsed_ms < 50, f"Took {elapsed_ms:.1f}ms, expected <50ms"
