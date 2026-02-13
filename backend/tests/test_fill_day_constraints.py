"""Tests for fill-day Tier 1 constraint validation."""

from unittest.mock import MagicMock

from app.planner.specialist_registry import FillDayRejection, validate_fill_day_placement


def _make_day_card(day_number: int, specialist_types: list[str] | None = None):
    """Create a mock DayCard with optional specialist blocks."""
    card = MagicMock()
    card.day_number = day_number
    card.blocks = []
    for st in specialist_types or []:
        block = MagicMock()
        block.specialist_type = st
        block.is_buffer = False
        card.blocks.append(block)
    return card


# ── No-fly buffer ─────────────────────────────────────────────────────


class TestNoflyBuffer:
    """Diving can't be placed too close to departure."""

    def test_diving_penultimate_day_rejected(self):
        # 7-day trip, departure day 7 → latest dive = day 5
        cards = [_make_day_card(i) for i in range(1, 8)]
        result = validate_fill_day_placement(
            target_day=6,
            specialist_type="diving",
            day_cards=cards,
            total_days=7,
            has_departure_flight=True,
        )
        assert isinstance(result, FillDayRejection)
        assert result.code == "NOFLY_BUFFER_VIOLATED"

    def test_diving_last_day_rejected(self):
        cards = [_make_day_card(i) for i in range(1, 8)]
        result = validate_fill_day_placement(
            target_day=7,
            specialist_type="diving",
            day_cards=cards,
            total_days=7,
            has_departure_flight=True,
        )
        assert result is not None
        assert result.code == "NOFLY_BUFFER_VIOLATED"

    def test_diving_on_safe_day_accepted(self):
        cards = [_make_day_card(i) for i in range(1, 8)]
        result = validate_fill_day_placement(
            target_day=5,
            specialist_type="diving",
            day_cards=cards,
            total_days=7,
            has_departure_flight=True,
        )
        assert result is None

    def test_diving_no_departure_flight_accepted(self):
        cards = [_make_day_card(i) for i in range(1, 8)]
        result = validate_fill_day_placement(
            target_day=6,
            specialist_type="diving",
            day_cards=cards,
            total_days=7,
            has_departure_flight=False,
        )
        assert result is None

    def test_diving_day_2_of_4_accepted(self):
        # 4-day trip: arrival(1), dive(2), buffer(3), departure(4) → day 2 is safe
        cards = [_make_day_card(i) for i in range(1, 5)]
        result = validate_fill_day_placement(
            target_day=2,
            specialist_type="diving",
            day_cards=cards,
            total_days=4,
            has_departure_flight=True,
        )
        assert result is None


# ── Cross-domain forward ──────────────────────────────────────────────


class TestCrossDomainForward:
    """Placing diving adjacent to altitude activities blocks."""

    def test_diving_adjacent_to_hiking_rejected(self):
        cards = [_make_day_card(3, ["hiking"]), _make_day_card(4)]
        result = validate_fill_day_placement(
            target_day=4,
            specialist_type="diving",
            day_cards=cards,
            total_days=7,
        )
        assert result is not None
        assert result.code == "ALTITUDE_AFTER_DIVE"

    def test_diving_adjacent_to_climbing_rejected(self):
        cards = [_make_day_card(5), _make_day_card(6, ["climbing"])]
        result = validate_fill_day_placement(
            target_day=5,
            specialist_type="diving",
            day_cards=cards,
            total_days=7,
        )
        assert result is not None
        assert result.code == "ALTITUDE_AFTER_DIVE"

    def test_diving_not_adjacent_to_hiking_accepted(self):
        # hiking on day 3, placing diving on day 5 (gap of 1 day) → OK
        cards = [_make_day_card(3, ["hiking"]), _make_day_card(5)]
        result = validate_fill_day_placement(
            target_day=5,
            specialist_type="diving",
            day_cards=cards,
            total_days=7,
        )
        assert result is None


# ── Cross-domain reverse ──────────────────────────────────────────────


class TestCrossDomainReverse:
    """Placing altitude activity adjacent to diving blocks."""

    def test_hiking_adjacent_to_diving_rejected(self):
        cards = [_make_day_card(3, ["diving"]), _make_day_card(4)]
        result = validate_fill_day_placement(
            target_day=4,
            specialist_type="hiking",
            day_cards=cards,
            total_days=7,
        )
        assert result is not None
        assert result.code == "ALTITUDE_AFTER_DIVE"

    def test_skiing_adjacent_to_diving_rejected(self):
        cards = [_make_day_card(3, ["diving"]), _make_day_card(4)]
        result = validate_fill_day_placement(
            target_day=4,
            specialist_type="skiing",
            day_cards=cards,
            total_days=7,
        )
        assert result is not None

    def test_climbing_adjacent_to_diving_rejected(self):
        cards = [_make_day_card(3), _make_day_card(4, ["diving"])]
        result = validate_fill_day_placement(
            target_day=3,
            specialist_type="climbing",
            day_cards=cards,
            total_days=7,
        )
        assert result is not None


# ── Non-constrained specialists ───────────────────────────────────────


class TestNonConstrainedSpecialist:
    """Surfing, cycling, etc. have no nofly/cross-domain → always pass."""

    def test_surfing_near_departure_accepted(self):
        cards = [_make_day_card(i) for i in range(1, 8)]
        result = validate_fill_day_placement(
            target_day=6,
            specialist_type="surfing",
            day_cards=cards,
            total_days=7,
        )
        assert result is None

    def test_cycling_adjacent_to_diving_accepted(self):
        # Cycling is NOT in diving's cross_domain_blocks targets
        cards = [_make_day_card(3, ["diving"]), _make_day_card(4)]
        result = validate_fill_day_placement(
            target_day=4,
            specialist_type="cycling",
            day_cards=cards,
            total_days=7,
        )
        assert result is None

    def test_unknown_specialist_passthrough(self):
        cards = [_make_day_card(i) for i in range(1, 8)]
        result = validate_fill_day_placement(
            target_day=6,
            specialist_type="unknown_activity",
            day_cards=cards,
            total_days=7,
        )
        assert result is None


# ── Surface interval (NOT blocking) ──────────────────────────────────


class TestSurfaceIntervalNotBlocking:
    """Back-to-back dives are valid — surface interval is a tag, not a block."""

    def test_diving_adjacent_to_diving_accepted(self):
        cards = [_make_day_card(3, ["diving"]), _make_day_card(4)]
        result = validate_fill_day_placement(
            target_day=4,
            specialist_type="diving",
            day_cards=cards,
            total_days=7,
        )
        assert result is None
