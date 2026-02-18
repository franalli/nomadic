# backend/tests/test_graph_plan_utils.py
"""
Unit tests for graph_plan_utils.py — pure utility functions for the /v1/graph_plan route.

All functions are pure (no I/O, no LLM calls), so no mocking is needed.

Covers:
- compute_today_iso: YYYY-MM-DD date string
- generate_request_id: UUID generation
- is_valid_thread_id: UUID validation
- ensure_thread_id: UUID coercion/generation
- sanitize_session_state: session dict sanitization
- normalize_currency: symbol/code → ISO-4217
- normalize_text: whitespace + Unicode NFC
- clamp_adults: min-1 clamping
- clamp_children: min-0 clamping
- clamp_budget: min-0 clamping with float coercion
- normalize_date: YYYY-MM-DD with ISO time-strip
- normalize_trip_inputs: full trip dict normalization
- validate_suggested_responses: filter + word-count rules
- truncate_assistant_message: graceful length clamping
"""

import re
import uuid

from app.graph_plan_utils import (
    clamp_adults,
    clamp_budget,
    clamp_children,
    compute_today_iso,
    ensure_thread_id,
    generate_request_id,
    is_valid_thread_id,
    normalize_currency,
    normalize_date,
    normalize_text,
    normalize_trip_inputs,
    sanitize_session_state,
    truncate_assistant_message,
    validate_suggested_responses,
)

# =============================================================================
# compute_today_iso
# =============================================================================


class TestComputeTodayIso:
    """Returns today's date string in YYYY-MM-DD format."""

    def test_returns_string(self) -> None:
        result = compute_today_iso()
        assert isinstance(result, str)

    def test_correct_length(self) -> None:
        result = compute_today_iso()
        assert len(result) == 10

    def test_yyyy_mm_dd_format(self) -> None:
        result = compute_today_iso()
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", result), f"Unexpected format: {result}"

    def test_valid_month_range(self) -> None:
        result = compute_today_iso()
        month = int(result[5:7])
        assert 1 <= month <= 12

    def test_valid_day_range(self) -> None:
        result = compute_today_iso()
        day = int(result[8:10])
        assert 1 <= day <= 31


# =============================================================================
# generate_request_id
# =============================================================================


class TestGenerateRequestId:
    """Generates a unique UUID string for request tracking."""

    def test_returns_string(self) -> None:
        result = generate_request_id()
        assert isinstance(result, str)

    def test_is_valid_uuid(self) -> None:
        result = generate_request_id()
        parsed = uuid.UUID(result)  # raises if invalid
        assert str(parsed) == result

    def test_uniqueness(self) -> None:
        """Two consecutive calls should not collide."""
        ids = {generate_request_id() for _ in range(20)}
        assert len(ids) == 20


# =============================================================================
# is_valid_thread_id
# =============================================================================


class TestIsValidThreadId:
    """Thread ID validation against UUID format."""

    def test_valid_uuid_returns_true(self) -> None:
        valid = str(uuid.uuid4())
        assert is_valid_thread_id(valid) is True

    def test_none_returns_false(self) -> None:
        assert is_valid_thread_id(None) is False

    def test_empty_string_returns_false(self) -> None:
        assert is_valid_thread_id("") is False

    def test_integer_returns_false(self) -> None:
        assert is_valid_thread_id(42) is False

    def test_random_string_returns_false(self) -> None:
        assert is_valid_thread_id("not-a-uuid") is False

    def test_partial_uuid_returns_false(self) -> None:
        partial = str(uuid.uuid4())[:20]
        assert is_valid_thread_id(partial) is False

    def test_dict_returns_false(self) -> None:
        assert is_valid_thread_id({"id": "abc"}) is False

    def test_list_returns_false(self) -> None:
        assert is_valid_thread_id([str(uuid.uuid4())]) is False


# =============================================================================
# ensure_thread_id
# =============================================================================


class TestEnsureThreadId:
    """Coerces invalid/missing thread IDs to a fresh UUID."""

    def test_valid_uuid_returned_unchanged(self) -> None:
        valid = str(uuid.uuid4())
        result = ensure_thread_id(valid)
        assert result == valid

    def test_none_returns_new_valid_uuid(self) -> None:
        result = ensure_thread_id(None)
        assert is_valid_thread_id(result)

    def test_empty_string_returns_new_uuid(self) -> None:
        result = ensure_thread_id("")
        assert is_valid_thread_id(result)

    def test_invalid_string_returns_new_uuid(self) -> None:
        result = ensure_thread_id("bogus-thread-id")
        assert is_valid_thread_id(result)

    def test_integer_returns_new_uuid(self) -> None:
        result = ensure_thread_id(99)
        assert is_valid_thread_id(result)

    def test_new_uuid_is_different_from_invalid_input(self) -> None:
        result = ensure_thread_id("bad-id")
        assert result != "bad-id"


# =============================================================================
# sanitize_session_state
# =============================================================================


class TestSanitizeSessionState:
    """Session state sanitization: strips dangerous keys, ensures defaults."""

    def test_none_returns_default_structure(self) -> None:
        result = sanitize_session_state(None)
        assert is_valid_thread_id(result["thread_id"])
        assert result["trip_inputs"] == {}
        assert result["metadata"] == {}
        assert result["flags"] == {}

    def test_none_returns_all_required_keys(self) -> None:
        result = sanitize_session_state(None)
        for key in (
            "thread_id",
            "trip_inputs",
            "metadata",
            "flags",
            "branches",
            "suggested_responses",
            "errors",
        ):
            assert key in result, f"Missing key: {key}"

    def test_valid_dict_preserves_thread_id(self) -> None:
        valid_id = str(uuid.uuid4())
        result = sanitize_session_state({"thread_id": valid_id})
        assert result["thread_id"] == valid_id

    def test_invalid_thread_id_replaced(self) -> None:
        result = sanitize_session_state({"thread_id": "not-valid"})
        assert is_valid_thread_id(result["thread_id"])
        assert result["thread_id"] != "not-valid"

    def test_strips_proto_pollution_key(self) -> None:
        raw = {"__proto__": {"isAdmin": True}, "thread_id": str(uuid.uuid4())}
        result = sanitize_session_state(raw)
        assert "__proto__" not in result

    def test_strips_constructor_key(self) -> None:
        raw = {"constructor": "evil", "thread_id": str(uuid.uuid4())}
        result = sanitize_session_state(raw)
        assert "constructor" not in result

    def test_strips_prototype_key(self) -> None:
        raw = {"prototype": "evil", "thread_id": str(uuid.uuid4())}
        result = sanitize_session_state(raw)
        assert "prototype" not in result

    def test_non_dict_treated_as_empty(self) -> None:
        result = sanitize_session_state("not-a-dict")  # type: ignore[arg-type]
        assert is_valid_thread_id(result["thread_id"])
        assert result["trip_inputs"] == {}

    def test_explicit_nulls_stored_in_metadata(self) -> None:
        tid = str(uuid.uuid4())
        result = sanitize_session_state({"thread_id": tid}, explicit_nulls={"budget", "start_date"})
        stored = result["metadata"]["explicit_nulls"]
        assert set(stored) == {"budget", "start_date"}

    def test_no_explicit_nulls_metadata_not_set(self) -> None:
        tid = str(uuid.uuid4())
        result = sanitize_session_state({"thread_id": tid})
        assert "explicit_nulls" not in result.get("metadata", {})

    def test_non_dict_trip_inputs_reset_to_empty(self) -> None:
        tid = str(uuid.uuid4())
        result = sanitize_session_state({"thread_id": tid, "trip_inputs": "bad"})
        assert result["trip_inputs"] == {}

    def test_non_dict_metadata_reset_to_empty(self) -> None:
        tid = str(uuid.uuid4())
        result = sanitize_session_state({"thread_id": tid, "metadata": 42})
        assert result["metadata"] == {}

    def test_extra_keys_preserved(self) -> None:
        """Non-dangerous unknown keys are kept for forward-compat."""
        tid = str(uuid.uuid4())
        result = sanitize_session_state({"thread_id": tid, "custom_key": "value"})
        assert result.get("custom_key") == "value"


# =============================================================================
# normalize_currency
# =============================================================================


class TestNormalizeCurrency:
    """Currency normalization to ISO-4217 code."""

    def test_dollar_symbol(self) -> None:
        assert normalize_currency("$") == "USD"

    def test_euro_symbol(self) -> None:
        assert normalize_currency("€") == "EUR"

    def test_pound_symbol(self) -> None:
        assert normalize_currency("£") == "GBP"

    def test_iso_code_uppercase_passthrough(self) -> None:
        assert normalize_currency("USD") == "USD"

    def test_iso_code_lowercase_normalized(self) -> None:
        assert normalize_currency("usd") == "USD"

    def test_iso_code_mixed_case(self) -> None:
        assert normalize_currency("Eur") == "EUR"

    def test_symbol_prefix_dollar_amount(self) -> None:
        """'$100' → 'USD' (extracts leading symbol)."""
        assert normalize_currency("$100") == "USD"

    def test_none_returns_none(self) -> None:
        assert normalize_currency(None) is None

    def test_integer_returns_none(self) -> None:
        assert normalize_currency(100) is None  # type: ignore[arg-type]

    def test_unknown_code_returns_none(self) -> None:
        assert normalize_currency("XYZ") is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_currency("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_currency("   ") is None

    def test_gbp_iso_code(self) -> None:
        assert normalize_currency("GBP") == "GBP"

    def test_jpy_iso_code(self) -> None:
        assert normalize_currency("JPY") == "JPY"


# =============================================================================
# normalize_text
# =============================================================================


class TestNormalizeText:
    """Text normalization: trim, whitespace collapse, Unicode NFC."""

    def test_trims_leading_trailing_whitespace(self) -> None:
        assert normalize_text("  hello  ") == "hello"

    def test_collapses_internal_spaces(self) -> None:
        assert normalize_text("hello   world") == "hello world"

    def test_collapses_tabs_and_newlines(self) -> None:
        result = normalize_text("hello\t\nworld")
        assert result == "hello world"

    def test_nfc_normalization(self) -> None:
        """Decomposed 'e + combining accent' → composed 'é'."""
        decomposed = "e\u0301"  # e + combining acute accent
        result = normalize_text(decomposed)
        assert result == "\xe9"  # precomposed é

    def test_non_string_returns_empty(self) -> None:
        assert normalize_text(None) == ""  # type: ignore[arg-type]
        assert normalize_text(42) == ""  # type: ignore[arg-type]
        assert normalize_text([]) == ""  # type: ignore[arg-type]

    def test_empty_string_returns_empty(self) -> None:
        assert normalize_text("") == ""

    def test_already_clean_text_unchanged(self) -> None:
        assert normalize_text("Bali") == "Bali"

    def test_preserves_unicode_characters(self) -> None:
        assert normalize_text("  Zürich  ") == "Zürich"


# =============================================================================
# clamp_adults
# =============================================================================


class TestClampAdults:
    """Adults must be at least 1; 0 or negative → None."""

    def test_valid_value_returned(self) -> None:
        assert clamp_adults(2) == 2

    def test_one_returned_as_is(self) -> None:
        assert clamp_adults(1) == 1

    def test_zero_returns_none(self) -> None:
        """0 is not > 0, so it does not qualify as a valid adult count."""
        assert clamp_adults(0) is None

    def test_negative_returns_none(self) -> None:
        assert clamp_adults(-3) is None

    def test_none_returns_none(self) -> None:
        assert clamp_adults(None) is None

    def test_string_int_coerced(self) -> None:
        assert clamp_adults("3") == 3

    def test_invalid_string_returns_none(self) -> None:
        assert clamp_adults("abc") is None

    def test_float_coerced(self) -> None:
        assert clamp_adults(2.9) == 2

    def test_large_value_returned(self) -> None:
        assert clamp_adults(10) == 10


# =============================================================================
# clamp_children
# =============================================================================


class TestClampChildren:
    """Children must be at least 0; negatives are clamped to 0."""

    def test_valid_value_returned(self) -> None:
        assert clamp_children(2) == 2

    def test_zero_returned_as_zero(self) -> None:
        assert clamp_children(0) == 0

    def test_negative_clamped_to_zero(self) -> None:
        assert clamp_children(-1) == 0

    def test_none_returns_none(self) -> None:
        assert clamp_children(None) is None

    def test_string_int_coerced(self) -> None:
        assert clamp_children("3") == 3

    def test_invalid_string_returns_none(self) -> None:
        assert clamp_children("abc") is None

    def test_float_truncated(self) -> None:
        assert clamp_children(1.9) == 1


# =============================================================================
# clamp_budget
# =============================================================================


class TestClampBudget:
    """Budget must be non-negative; negatives clamped to 0. Accepts float strings."""

    def test_valid_integer_returned(self) -> None:
        assert clamp_budget(5000) == 5000

    def test_zero_returned(self) -> None:
        assert clamp_budget(0) == 0

    def test_negative_clamped_to_zero(self) -> None:
        assert clamp_budget(-100) == 0

    def test_float_string_coerced(self) -> None:
        assert clamp_budget("5000.99") == 5000

    def test_integer_string_coerced(self) -> None:
        assert clamp_budget("3000") == 3000

    def test_none_returns_none(self) -> None:
        assert clamp_budget(None) is None

    def test_invalid_string_returns_none(self) -> None:
        assert clamp_budget("expensive") is None

    def test_float_truncated_to_int(self) -> None:
        result = clamp_budget(1500.75)
        assert result == 1500
        assert isinstance(result, int)


# =============================================================================
# normalize_date
# =============================================================================


class TestNormalizeDate:
    """Normalizes dates to YYYY-MM-DD, stripping ISO time suffix."""

    def test_already_normalized_passthrough(self) -> None:
        assert normalize_date("2026-02-01") == "2026-02-01"

    def test_iso_with_z_suffix_stripped(self) -> None:
        assert normalize_date("2026-02-01T00:00:00.000Z") == "2026-02-01"

    def test_iso_with_timezone_stripped(self) -> None:
        assert normalize_date("2026-02-01T12:00:00+00:00") == "2026-02-01"

    def test_none_returns_none(self) -> None:
        assert normalize_date(None) is None

    def test_invalid_string_returns_none(self) -> None:
        assert normalize_date("not-a-date") is None

    def test_empty_string_returns_none(self) -> None:
        assert normalize_date("") is None

    def test_whitespace_only_returns_none(self) -> None:
        assert normalize_date("   ") is None

    def test_non_string_returns_none(self) -> None:
        assert normalize_date(20260201) is None  # type: ignore[arg-type]

    def test_slashed_format_returns_none(self) -> None:
        """Non-standard format should not be returned."""
        result = normalize_date("2026/02/01")
        assert result is None

    def test_valid_end_of_year(self) -> None:
        assert normalize_date("2026-12-31") == "2026-12-31"


# =============================================================================
# normalize_trip_inputs
# =============================================================================


class TestNormalizeTripInputs:
    """Full trip dict normalization composing all individual normalizers."""

    def test_non_dict_returns_empty(self) -> None:
        assert normalize_trip_inputs("bad") == {}  # type: ignore[arg-type]
        assert normalize_trip_inputs(None) == {}  # type: ignore[arg-type]
        assert normalize_trip_inputs([]) == {}  # type: ignore[arg-type]

    def test_destination_text_normalized(self) -> None:
        result = normalize_trip_inputs({"destination": "  Bali  "})
        assert result["destination"] == "Bali"

    def test_dates_normalized(self) -> None:
        result = normalize_trip_inputs(
            {
                "start_date": "2026-03-01T00:00:00.000Z",
                "end_date": "2026-03-08",
            }
        )
        assert result["start_date"] == "2026-03-01"
        assert result["end_date"] == "2026-03-08"

    def test_adults_clamped(self) -> None:
        result = normalize_trip_inputs({"adults": 0})
        assert result["adults"] is None

    def test_children_clamped(self) -> None:
        result = normalize_trip_inputs({"children": -2})
        assert result["children"] == 0

    def test_budget_clamped(self) -> None:
        result = normalize_trip_inputs({"budget": -500})
        assert result["budget"] == 0

    def test_budget_float_string_coerced(self) -> None:
        result = normalize_trip_inputs({"budget": "7500.50"})
        assert result["budget"] == 7500

    def test_booking_types_passed_through(self) -> None:
        result = normalize_trip_inputs({"booking_types": ["flights", "hotels"]})
        assert result["booking_types"] == ["flights", "hotels"]

    def test_hotel_settings_passed_through(self) -> None:
        result = normalize_trip_inputs({"hotel_settings": {"min_stars": 4}})
        assert result["hotel_settings"] == {"min_stars": 4}

    def test_activity_settings_passed_through(self) -> None:
        result = normalize_trip_inputs({"activity_settings": {"categories": ["diving"]}})
        assert result["activity_settings"] == {"categories": ["diving"]}

    def test_empty_dict_returns_empty(self) -> None:
        assert normalize_trip_inputs({}) == {}

    def test_null_destination_preserved(self) -> None:
        result = normalize_trip_inputs({"destination": None})
        assert result["destination"] is None

    def test_currency_normalized(self) -> None:
        result = normalize_trip_inputs({"currency": "€"})
        assert result["currency"] == "EUR"

    def test_invalid_currency_excluded(self) -> None:
        result = normalize_trip_inputs({"currency": "INVALID"})
        assert "currency" not in result

    def test_invalid_date_returns_none(self) -> None:
        result = normalize_trip_inputs({"start_date": "bad-date"})
        assert result["start_date"] is None


# =============================================================================
# validate_suggested_responses
# =============================================================================


class TestValidateSuggestedResponses:
    """Filters chip responses: max 3, no question marks, 1-8 words each."""

    def test_max_three_returned(self) -> None:
        items = ["Bali", "Thailand", "Japan", "Vietnam", "Greece"]
        result = validate_suggested_responses(items)
        assert len(result) <= 3

    def test_question_mark_filtered(self) -> None:
        result = validate_suggested_responses(["Is Bali safe?", "Thailand"])
        assert all("?" not in r for r in result)
        assert "Thailand" in result

    def test_over_eight_words_filtered(self) -> None:
        long_item = "I want to go to Bali for a diving holiday this summer"
        result = validate_suggested_responses([long_item, "Bali"])
        assert long_item not in result
        assert "Bali" in result

    def test_empty_strings_filtered(self) -> None:
        result = validate_suggested_responses(["", "Bali", "  "])
        assert "" not in result
        assert "Bali" in result

    def test_non_list_returns_empty(self) -> None:
        assert validate_suggested_responses("Bali") == []
        assert validate_suggested_responses(None) == []
        assert validate_suggested_responses(42) == []

    def test_valid_single_word_accepted(self) -> None:
        """Single-word destinations like 'Norway' are valid."""
        result = validate_suggested_responses(["Norway"])
        assert result == ["Norway"]

    def test_valid_eight_word_item_accepted(self) -> None:
        eight_words = "Bali diving trip with a budget of five"
        result = validate_suggested_responses([eight_words])
        assert eight_words in result

    def test_non_string_items_skipped(self) -> None:
        result = validate_suggested_responses([123, "Bali", None])
        assert result == ["Bali"]

    def test_empty_list_returns_empty(self) -> None:
        assert validate_suggested_responses([]) == []

    def test_order_preserved_up_to_three(self) -> None:
        items = ["Bali", "Thailand", "Japan"]
        result = validate_suggested_responses(items)
        assert result == ["Bali", "Thailand", "Japan"]


# =============================================================================
# truncate_assistant_message
# =============================================================================


class TestTruncateAssistantMessage:
    """Truncates long assistant messages gracefully at sentence or word boundaries."""

    def test_short_message_returned_unchanged(self) -> None:
        msg = "Hello! Here is your trip plan."
        result = truncate_assistant_message(msg)
        assert result == msg

    def test_none_returns_empty_string(self) -> None:
        assert truncate_assistant_message(None) == ""

    def test_non_string_converted(self) -> None:
        result = truncate_assistant_message(42)
        assert isinstance(result, str)
        assert result == "42"

    def test_very_long_message_truncated(self) -> None:
        """A message far exceeding max_len must be truncated."""
        # settings.assistant_msg_max_len = 2000 by default
        long_msg = "This is a sentence. " * 500  # ~10000 chars
        result = truncate_assistant_message(long_msg)
        assert len(result) <= 2100  # allow slight overshoot at sentence boundary

    def test_truncated_result_ends_cleanly(self) -> None:
        """Result should end with punctuation or '...' — not mid-word."""
        long_msg = "word " * 600  # no sentence punctuation
        result = truncate_assistant_message(long_msg)
        assert result.endswith("...") or result[-1] in ".!?"

    def test_empty_string_returned_unchanged(self) -> None:
        assert truncate_assistant_message("") == ""

    def test_exactly_at_max_len_not_truncated(self) -> None:
        from app.config import settings

        msg = "x" * settings.assistant_msg_max_len
        result = truncate_assistant_message(msg)
        assert len(result) == settings.assistant_msg_max_len

    def test_truncated_length_is_bounded(self) -> None:
        from app.config import settings

        long_msg = "a" * (settings.assistant_msg_max_len * 2)
        result = truncate_assistant_message(long_msg)
        # Result must be shorter than original
        assert len(result) < len(long_msg)
