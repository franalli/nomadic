# backend/tests/test_router_utils.py
"""
Unit tests for router_utils.py — routing helpers that determine entire flow path.

Tests cover:
- _check_exact_match_greeting: greeting detection (saves LLM calls)
- _detect_origin_from_message: origin city extraction with normalization
- get_new_specialists_from_text: specialist detection from user text
- _normalize_city_name (from router_extraction): city name normalization
- _validate_extraction (from router_extraction): date bumps, field normalization
"""

from datetime import date, timedelta

import pytest

from app.planner.nodes.router_extraction import (
    _normalize_city_name,
    _validate_extraction,
)
from app.planner.nodes.router_utils import (
    _check_exact_match_greeting,
    _detect_origin_from_message,
    get_new_specialists_from_text,
)

# =============================================================================
# _check_exact_match_greeting
# =============================================================================


class TestCheckExactMatchGreeting:
    """Greeting detection saves an LLM call (~300ms, ~150 tokens)."""

    @pytest.mark.parametrize(
        "text",
        ["hi", "hello", "hey", "Hi!", "HELLO", "  hi  ", "good morning", "thanks", "bye"],
    )
    def test_matches_known_greetings(self, text: str) -> None:
        result = _check_exact_match_greeting(text)
        assert result is not None
        assert result.intent == "GREETING"
        assert result.confidence == 1.0

    @pytest.mark.parametrize(
        "text",
        [
            "I want to go to Bali",
            "hi there how are you",
            "hello can you help me plan a trip",
            "from rome",
            "diving trip",
            "",
        ],
    )
    def test_rejects_non_greetings(self, text: str) -> None:
        result = _check_exact_match_greeting(text)
        assert result is None

    def test_case_insensitive(self) -> None:
        assert _check_exact_match_greeting("HI") is not None
        assert _check_exact_match_greeting("Hello") is not None
        assert _check_exact_match_greeting("GOOD MORNING") is not None


# =============================================================================
# _detect_origin_from_message
# =============================================================================


class TestDetectOriginFromMessage:
    """Origin detection must run BEFORE exploration mode to avoid misrouting."""

    def test_from_city(self) -> None:
        assert _detect_origin_from_message("from rome") == "Rome"

    def test_flying_from(self) -> None:
        assert _detect_origin_from_message("flying from london") == "London"

    def test_leaving_from(self) -> None:
        assert _detect_origin_from_message("leaving from NYC") == "New York"

    def test_departing_from(self) -> None:
        assert _detect_origin_from_message("departing from paris") == "Paris"

    def test_i_am_from(self) -> None:
        result = _detect_origin_from_message("i'm from san francisco")
        assert result == "San Francisco"

    def test_truncates_at_to(self) -> None:
        """'from rome to bali' → origin is Rome, not 'rome to bali'."""
        result = _detect_origin_from_message("from rome to bali")
        assert result == "Rome"

    def test_truncates_at_date_token(self) -> None:
        """'from rome feb 11' → origin is Rome, not 'rome feb 11'."""
        result = _detect_origin_from_message("from rome feb 11")
        assert result == "Rome"

    def test_no_origin_pattern(self) -> None:
        assert _detect_origin_from_message("tell me about rome") is None

    def test_no_from_keyword(self) -> None:
        assert _detect_origin_from_message("I want to go to Bali") is None

    def test_strips_punctuation(self) -> None:
        result = _detect_origin_from_message("from london!")
        assert result == "London"

    def test_nyc_abbreviation(self) -> None:
        result = _detect_origin_from_message("from NYC")
        assert result == "New York"

    def test_la_abbreviation(self) -> None:
        result = _detect_origin_from_message("from LA")
        assert result == "Los Angeles"


# =============================================================================
# get_new_specialists_from_text
# =============================================================================


class TestGetNewSpecialistsFromText:
    """Specialist detection determines which domain experts get activated."""

    def test_detects_diving(self) -> None:
        result = get_new_specialists_from_text("I want to go diving in Bali", [])
        assert "diving" in result

    def test_detects_hiking(self) -> None:
        result = get_new_specialists_from_text("hiking trip to Nepal", [])
        assert "hiking" in result

    def test_skips_existing(self) -> None:
        result = get_new_specialists_from_text("diving trip", ["diving"])
        assert "diving" not in result

    def test_detects_multiple(self) -> None:
        result = get_new_specialists_from_text("I want diving and hiking", [])
        assert "diving" in result
        assert "hiking" in result

    def test_no_specialists(self) -> None:
        result = get_new_specialists_from_text("I want to go to Paris", [])
        assert result == []

    def test_case_insensitive(self) -> None:
        result = get_new_specialists_from_text("DIVING TRIP", [])
        assert "diving" in result


# =============================================================================
# _normalize_city_name
# =============================================================================


class TestNormalizeCityName:
    """City name normalization ensures consistent cache keys."""

    def test_removes_country_suffix(self) -> None:
        assert _normalize_city_name("Paris, France") == "Paris"

    def test_removes_us_suffix(self) -> None:
        assert _normalize_city_name("New York, USA") == "New York"

    def test_removes_state_suffix(self) -> None:
        assert _normalize_city_name("Miami, FL") == "Miami"

    def test_expands_nyc(self) -> None:
        assert _normalize_city_name("NYC") == "New York"

    def test_expands_la(self) -> None:
        assert _normalize_city_name("LA") == "Los Angeles"

    def test_expands_sf(self) -> None:
        assert _normalize_city_name("SF") == "San Francisco"

    def test_passthrough_clean_name(self) -> None:
        assert _normalize_city_name("Tokyo") == "Tokyo"

    def test_empty_string(self) -> None:
        assert _normalize_city_name("") == ""

    def test_strips_whitespace(self) -> None:
        assert _normalize_city_name("  Bali  ") == "Bali"

    def test_case_insensitive_suffix(self) -> None:
        assert _normalize_city_name("rome, italy") == "rome"


# =============================================================================
# _validate_extraction — date bumps, field normalization
# =============================================================================


class TestValidateExtraction:
    """Extraction validation catches LLM errors and normalizes data."""

    def _today(self) -> str:
        return date.today().isoformat()

    def test_valid_dates_pass_through(self) -> None:
        future = date.today() + timedelta(days=30)
        end = future + timedelta(days=7)
        extracted = {
            "start_date": future.isoformat(),
            "end_date": end.isoformat(),
        }
        result = _validate_extraction(extracted, self._today())
        assert result["start_date"] == future.isoformat()
        assert result["end_date"] == end.isoformat()

    def test_invalid_date_format_nullified(self) -> None:
        extracted = {"start_date": "not-a-date", "end_date": "2025-13-01"}
        result = _validate_extraction(extracted, self._today())
        assert result["start_date"] is None
        assert result["end_date"] is None

    def test_swaps_reversed_dates(self) -> None:
        future_start = date.today() + timedelta(days=30)
        future_end = future_start + timedelta(days=7)
        extracted = {
            "start_date": future_end.isoformat(),
            "end_date": future_start.isoformat(),
        }
        result = _validate_extraction(extracted, self._today())
        assert result["start_date"] == future_start.isoformat()
        assert result["end_date"] == future_end.isoformat()

    def test_past_dates_auto_bumped(self) -> None:
        """Past dates get +1 year bump (user says 'Feb 15' meaning next Feb)."""
        past = date.today() - timedelta(days=30)
        extracted = {"start_date": past.isoformat()}
        result = _validate_extraction(extracted, self._today())
        bumped = date(past.year + 1, past.month, past.day)
        assert result["start_date"] == bumped.isoformat()
        assert len(result["date_auto_adjustments"]) >= 1
        assert result["date_auto_adjustments"][0]["reason"] == "past_date_auto_bumped"

    def test_start_bump_cascades_to_end(self) -> None:
        """When start bumps to next year, end should follow to preserve range."""
        past_start = date.today() - timedelta(days=60)
        past_end = date.today() - timedelta(days=53)
        extracted = {
            "start_date": past_start.isoformat(),
            "end_date": past_end.isoformat(),
        }
        result = _validate_extraction(extracted, self._today())
        # Both should be bumped
        assert result["start_date"] > self._today()
        assert result["end_date"] > self._today()
        # Range should be preserved (~7 days)
        from datetime import datetime

        s = datetime.strptime(result["start_date"], "%Y-%m-%d").date()
        e = datetime.strptime(result["end_date"], "%Y-%m-%d").date()
        assert (e - s).days == 7

    def test_activity_categories_lowercased(self) -> None:
        extracted = {"activity_categories": ["DIVING", "Hiking", "  skiing "]}
        result = _validate_extraction(extracted, self._today())
        assert result["activity_categories"] == ["diving", "hiking", "skiing"]

    def test_adults_minimum_one(self) -> None:
        extracted = {"adults": 0}
        result = _validate_extraction(extracted, self._today())
        assert result["adults"] == 1

    def test_children_minimum_zero(self) -> None:
        extracted = {"children": -1}
        result = _validate_extraction(extracted, self._today())
        assert result["children"] == 0

    def test_destination_normalized(self) -> None:
        extracted = {"destination": "Paris, France"}
        result = _validate_extraction(extracted, self._today())
        assert result["destination"] == "Paris"

    def test_origin_normalized(self) -> None:
        extracted = {"origin": "NYC"}
        result = _validate_extraction(extracted, self._today())
        assert result["origin"] == "New York"

    def test_future_dates_not_bumped(self) -> None:
        future = date.today() + timedelta(days=60)
        extracted = {"start_date": future.isoformat()}
        result = _validate_extraction(extracted, self._today())
        assert result["start_date"] == future.isoformat()
        assert result["date_auto_adjustments"] == []
