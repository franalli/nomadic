"""Unit tests for synthesizer.py pure functions — grounding, stripping, and response-type logic.

Covers functions NOT already tested in test_synthesizer_template_contract.py:
- _get_response_type
- _canonicalize_activity_category
- _strip_day_pref_recap_from_sentence
- _ground_specialist_update_response
- _strip_tile_count_claim_sentences
- _build_authoritative_tile_count_sentence
- _strip_hallucinated_flight_count_claims
- _extract_claimed_tile_categories
"""

from __future__ import annotations

import importlib

from langchain_core.messages import HumanMessage

from app.planner.state import GraphState, TripPlan

synth = importlib.import_module("app.planner.nodes.synthesizer")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _state(
    *,
    destination: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    metadata: dict | None = None,
    tiles: dict | None = None,
) -> GraphState:
    """Build a minimal GraphState for testing."""
    tp = TripPlan(destination=destination, start_date=start_date, end_date=end_date)
    s = GraphState(trip_plan=tp)
    s.messages = [HumanMessage(content="test")]
    if metadata:
        s.metadata.update(metadata)
    if tiles:
        s.tiles = tiles
    return s


def _full_state(*, metadata: dict | None = None, tiles: dict | None = None) -> GraphState:
    """State with all core trip fields populated (destination + dates)."""
    return _state(
        destination="Bali",
        start_date="2026-06-01",
        end_date="2026-06-10",
        metadata=metadata,
        tiles=tiles,
    )


# ===========================================================================
# 1. _get_response_type
# ===========================================================================


class TestGetResponseType:
    def test_gate_blocked_returns_planning(self) -> None:
        s = _state(metadata={"short_circuit_type": "gate_blocked"})
        assert synth._get_response_type(s) == "planning"

    def test_greeting_short_circuit(self) -> None:
        s = _state(metadata={"short_circuit_type": "greeting"})
        assert synth._get_response_type(s) == "greeting"

    def test_reset_short_circuit(self) -> None:
        s = _state(metadata={"short_circuit_type": "reset"})
        assert synth._get_response_type(s) == "greeting"

    def test_full_trip_with_added_categories_no_structural_change(self) -> None:
        """Category-only add after plan given => specialist_update."""
        s = _full_state(
            metadata={
                "_planning_response_given": True,
                "added_categories": ["surfing"],
            }
        )
        assert synth._get_response_type(s) == "specialist_update"

    def test_full_trip_constraint_violations(self) -> None:
        s = _full_state(
            metadata={
                "constraint_violations": [{"code": "BUDGET_EXCEEDED"}],
            }
        )
        assert synth._get_response_type(s) == "planning"

    def test_full_trip_first_time_returns_planning(self) -> None:
        s = _full_state()
        assert synth._get_response_type(s) == "planning"

    def test_exploration_mode(self) -> None:
        s = _state(metadata={"exploration_mode": True})
        assert synth._get_response_type(s) == "exploration"

    def test_specialist_hint_returns_specialist_update(self) -> None:
        s = _state(
            destination="Rome",
            metadata={"specialist_hint": "diving"},
        )
        assert synth._get_response_type(s) == "specialist_update"

    def test_specialist_just_ran_returns_specialist_update(self) -> None:
        s = _state(
            destination="Rome",
            metadata={"specialist_just_ran": True},
        )
        # specialist_just_ran is a structural change, but without full trip (no dates)
        # => falls through to specialist_hint/specialist_just_ran check
        assert synth._get_response_type(s) == "specialist_update"

    def test_destination_only_returns_specialist_update(self) -> None:
        s = _state(destination="Tokyo")
        assert synth._get_response_type(s) == "specialist_update"

    def test_no_destination_returns_exploration(self) -> None:
        s = _state()
        assert synth._get_response_type(s) == "exploration"

    def test_full_trip_with_structural_change_after_planning_given(self) -> None:
        """Significant re-plan with specialist_just_ran => planning."""
        s = _full_state(
            metadata={
                "_planning_response_given": True,
                "specialist_just_ran": True,
            }
        )
        assert synth._get_response_type(s) == "planning"

    def test_full_trip_date_change_after_planning_given(self) -> None:
        """Date applied fields trigger planning (structural change)."""
        s = _full_state(
            metadata={
                "_planning_response_given": True,
                "turn_applied_fields": ["end_date"],
            }
        )
        assert synth._get_response_type(s) == "planning"


# ===========================================================================
# 2. _canonicalize_activity_category
# ===========================================================================


class TestCanonicalizeActivityCategory:
    def test_empty_string(self) -> None:
        assert synth._canonicalize_activity_category("") == ""

    def test_none_input(self) -> None:
        assert synth._canonicalize_activity_category(None) == ""

    def test_normal_label_lowercased(self) -> None:
        assert synth._canonicalize_activity_category("Diving") == "diving"

    def test_whitespace_normalized(self) -> None:
        result = synth._canonicalize_activity_category("  scuba   diving  ")
        # Should be lowercase, single-spaced
        assert "  " not in result

    def test_known_alias_resolved(self) -> None:
        # "scuba diving" is a known alias for "diving"
        result = synth._canonicalize_activity_category("scuba diving")
        assert result == "diving"

    def test_unknown_label_passes_through(self) -> None:
        assert synth._canonicalize_activity_category("zorbing") == "zorbing"


# ===========================================================================
# 3. _strip_day_pref_recap_from_sentence
# ===========================================================================


class TestStripDayPrefRecap:
    def test_no_pattern_returns_unchanged(self) -> None:
        s = "Your trip to Bali is all set."
        assert synth._strip_day_pref_recap_from_sentence(s) == s

    def test_pattern_with_days_stripped(self) -> None:
        s = (
            "Trip extends to March 2, allowing more time to enjoy "
            "**3 days of diving** and **2 days of surfing**."
        )
        result = synth._strip_day_pref_recap_from_sentence(s)
        assert "3 days of diving" not in result
        assert "2 days of surfing" not in result
        assert "extends to March 2" in result

    def test_pattern_with_cut_token_before(self) -> None:
        s = "Your trip now extends to March 2, with **3 days of diving** in the itinerary."
        result = synth._strip_day_pref_recap_from_sentence(s)
        assert "3 days of diving" not in result
        # Should cut at the ", with" token
        assert "extends to March 2" in result

    def test_empty_input(self) -> None:
        assert synth._strip_day_pref_recap_from_sentence("") == ""

    def test_none_input(self) -> None:
        assert synth._strip_day_pref_recap_from_sentence(None) == ""

    def test_result_ends_with_punctuation(self) -> None:
        s = "Trip updated, featuring **5 days of hiking** on the trails."
        result = synth._strip_day_pref_recap_from_sentence(s)
        assert result.endswith(".")


# ===========================================================================
# 4. _ground_specialist_update_response
# ===========================================================================


class TestGroundSpecialistUpdateResponse:
    def test_non_specialist_update_passthrough(self) -> None:
        msg = "Some long message with many sentences."
        assert synth._ground_specialist_update_response(msg, "planning") == msg

    def test_empty_message(self) -> None:
        assert synth._ground_specialist_update_response("", "specialist_update") == ""

    def test_truncated_to_max_two_sentences(self) -> None:
        msg = "First sentence here. Second sentence there. Third sentence extra. Fourth one too."
        result = synth._ground_specialist_update_response(msg, "specialist_update")
        # Split result and count sentences
        sentences = [s.strip() for s in result.split(".") if s.strip()]
        assert len(sentences) <= 2

    def test_day_pref_recap_stripped(self) -> None:
        msg = "Your trip now includes **3 days of diving** and **2 days of surfing**. Enjoy Bali."
        result = synth._ground_specialist_update_response(msg, "specialist_update")
        assert "3 days of diving" not in result

    def test_single_sentence_preserved(self) -> None:
        msg = "Plan updated successfully."
        result = synth._ground_specialist_update_response(msg, "specialist_update")
        assert "Plan updated successfully." in result


# ===========================================================================
# 5. _strip_tile_count_claim_sentences
# ===========================================================================


class TestStripTileCountClaimSentences:
    def test_no_tile_claims(self) -> None:
        msg = "Your trip to Bali looks amazing."
        text, cats = synth._strip_tile_count_claim_sentences(msg)
        assert text == msg
        assert cats == set()

    def test_hotel_claim_stripped(self) -> None:
        msg = "Great plan. Found **3 hotels** for your stay."
        text, cats = synth._strip_tile_count_claim_sentences(msg)
        assert "hotels" not in text
        assert "hotels" in cats

    def test_multiple_tile_claims(self) -> None:
        msg = "Plan ready. Found **3 hotels** nearby. Showing **5 activities** for you."
        text, cats = synth._strip_tile_count_claim_sentences(msg)
        assert "hotels" in cats
        assert "activities" in cats
        assert "Plan ready." in text

    def test_empty_message(self) -> None:
        text, cats = synth._strip_tile_count_claim_sentences("")
        assert text == ""
        assert cats == set()


# ===========================================================================
# 6. _build_authoritative_tile_count_sentence
# ===========================================================================


class TestBuildAuthoritativeTileCountSentence:
    def test_single_category_singular(self) -> None:
        s = _state(tiles={"hotels": [{"id": "h1"}], "flights": [], "activities": []})
        result = synth._build_authoritative_tile_count_sentence(s, {"hotels"})
        assert result == "Found **1 hotel**."

    def test_two_categories(self) -> None:
        s = _state(
            tiles={
                "hotels": [{"id": "h1"}, {"id": "h2"}, {"id": "h3"}],
                "activities": [
                    {"id": "a1"},
                    {"id": "a2"},
                    {"id": "a3"},
                    {"id": "a4"},
                    {"id": "a5"},
                ],
                "flights": [],
            }
        )
        result = synth._build_authoritative_tile_count_sentence(s, {"hotels", "activities"})
        assert result == "Found **3 hotels** and **5 activities**."

    def test_three_categories(self) -> None:
        s = _state(
            tiles={
                "hotels": [{"id": "h1"}, {"id": "h2"}, {"id": "h3"}],
                "flights": [{"id": "f1"}, {"id": "f2"}],
                "activities": [
                    {"id": "a1"},
                    {"id": "a2"},
                    {"id": "a3"},
                    {"id": "a4"},
                    {"id": "a5"},
                ],
            }
        )
        result = synth._build_authoritative_tile_count_sentence(
            s, {"hotels", "flights", "activities"}
        )
        assert result == "Found **3 hotels**, **2 flights**, and **5 activities**."

    def test_category_with_zero_count_skipped(self) -> None:
        s = _state(tiles={"hotels": [{"id": "h1"}], "flights": [], "activities": []})
        result = synth._build_authoritative_tile_count_sentence(s, {"hotels", "flights"})
        # flights has 0 => skipped
        assert result == "Found **1 hotel**."

    def test_empty_categories(self) -> None:
        s = _state(tiles={"hotels": [{"id": "h1"}], "flights": [], "activities": []})
        result = synth._build_authoritative_tile_count_sentence(s, set())
        assert result == ""

    def test_all_zero_counts(self) -> None:
        s = _state(tiles={"hotels": [], "flights": [], "activities": []})
        result = synth._build_authoritative_tile_count_sentence(s, {"hotels", "flights"})
        assert result == ""


# ===========================================================================
# 7. _strip_hallucinated_flight_count_claims
# ===========================================================================


class TestStripHallucinatedFlightCountClaims:
    def test_flight_claim_stripped(self) -> None:
        msg = "Plan updated. Found **2 flights** for your trip."
        result = synth._strip_hallucinated_flight_count_claims(msg)
        assert "flights" not in result
        assert "Plan updated." in result

    def test_hotel_claim_preserved(self) -> None:
        msg = "Found **3 hotels** for your stay."
        result = synth._strip_hallucinated_flight_count_claims(msg)
        assert "3 hotels" in result

    def test_mixed_claims_only_flights_stripped(self) -> None:
        msg = "Found **3 hotels** nearby. Found **2 flights** for you."
        result = synth._strip_hallucinated_flight_count_claims(msg)
        assert "3 hotels" in result
        assert "2 flights" not in result

    def test_no_claims_unchanged(self) -> None:
        msg = "Your Bali adventure awaits."
        result = synth._strip_hallucinated_flight_count_claims(msg)
        assert result == msg

    def test_empty_message(self) -> None:
        result = synth._strip_hallucinated_flight_count_claims("")
        assert result == ""


# ===========================================================================
# 8. _extract_claimed_tile_categories
# ===========================================================================


class TestExtractClaimedTileCategories:
    def test_hotel_keyword_with_number(self) -> None:
        result = synth._extract_claimed_tile_categories("Found 3 hotels nearby.")
        assert "hotels" in result

    def test_activity_keyword_with_number(self) -> None:
        result = synth._extract_claimed_tile_categories("Showing 5 activities for you.")
        assert "activities" in result

    def test_flight_keyword_with_claim_verb(self) -> None:
        result = synth._extract_claimed_tile_categories("Now showing flights for your trip.")
        assert "flights" in result

    def test_no_count_no_verb_returns_empty(self) -> None:
        result = synth._extract_claimed_tile_categories("Your trip to Bali looks great.")
        assert result == set()

    def test_empty_sentence(self) -> None:
        result = synth._extract_claimed_tile_categories("")
        assert result == set()

    def test_none_sentence(self) -> None:
        result = synth._extract_claimed_tile_categories(None)
        assert result == set()

    def test_option_hint_triggers_detection(self) -> None:
        result = synth._extract_claimed_tile_categories("Hotel options are available.")
        assert "hotels" in result

    def test_multiple_categories_in_one_sentence(self) -> None:
        result = synth._extract_claimed_tile_categories(
            "Found 3 hotels and 2 flights for your trip."
        )
        assert "hotels" in result
        assert "flights" in result
