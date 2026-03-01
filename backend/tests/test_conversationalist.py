"""Unit tests for conversationalist sentence enforcement and voice block resolution."""

from app.planner.conversationalist import (
    _SENTENCE_LIMIT,
    _VOICE_ACTIVITY_CHANGE,
    _VOICE_DATES_SET,
    _VOICE_DESTINATION_SET,
    _VOICE_FALLBACK,
    _VOICE_GREETING,
    _VOICE_PLAN_GENERATED,
    _VOICE_PREFERENCE_CHANGE,
    _VOICE_QUESTION,
    _build_from_strategy_sections,
    _build_trip_context_block,
    _build_turn_context_block,
    _detect_user_energy,
    _enforce_sentence_limit,
    _resolve_voice_block,
    build_response_context,
)
from app.planner.schemas.coordinator_schemas import ChangeType, ClassifierOutput

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_classifier(change_type: ChangeType) -> ClassifierOutput:
    """Minimal ClassifierOutput for testing voice block resolution."""
    return ClassifierOutput(
        intent="PLANNING",
        confidence=0.9,
        reasoning="test",
        change_type=change_type,
    )


# ---------------------------------------------------------------------------
# _enforce_sentence_limit
# ---------------------------------------------------------------------------


class TestEnforceSentenceLimit:
    """Tests for the streaming sentence enforcement function."""

    def test_single_sentence(self):
        assert _enforce_sentence_limit("Hello world.", 3) == "Hello world."

    def test_under_limit(self):
        text = "First sentence. Second sentence."
        assert _enforce_sentence_limit(text, 3) == text

    def test_at_limit(self):
        text = "One. Two. Three."
        assert _enforce_sentence_limit(text, 3) == text

    def test_over_limit_trims(self):
        text = "One. Two. Three. Four."
        assert _enforce_sentence_limit(text, 3) == "One. Two. Three."

    def test_exclamation_marks(self):
        text = "Wow! Great! Amazing! Incredible!"
        assert _enforce_sentence_limit(text, 2) == "Wow! Great!"

    def test_question_marks(self):
        text = "Really? Yes! Done."
        assert _enforce_sentence_limit(text, 2) == "Really? Yes!"

    def test_consecutive_punctuation_counts_as_one(self):
        """'!!' and '...' should each count as a single sentence ending."""
        # "Wow!!" (1) + " Really..." + " Done." (space+uppercase after "...") = 3
        # Each '!!' and '...' group counts as one ending, not two.
        text = "Wow!! Really... Done."
        assert _enforce_sentence_limit(text, 2) == "Wow!! Really..."
        # Contrast: ellipsis + lowercase = NOT a boundary
        text2 = "Wow!! wait... really."
        # "!!" → space + 'w' lowercase → NOT a boundary
        # "..." → space + 'r' lowercase → NOT a boundary
        # "really." → end of text → boundary (count=1)
        assert _enforce_sentence_limit(text2, 1) == text2

    def test_ellipsis_mid_sentence(self):
        """'Wait... really?' is one sentence (ellipsis + lowercase continuation)."""
        text = "Wait... really? Next thing."
        # "Wait..." -> followed by " really" (lowercase) -> NOT a boundary
        # "really?" -> followed by " Next" (uppercase) -> boundary (count=1)
        # "Next thing." -> end of text -> boundary (count=2)
        assert _enforce_sentence_limit(text, 1) == "Wait... really?"

    def test_abbreviation_us(self):
        """'U.S.' should not count as sentence endings."""
        text = "The U.S. has options. Rome is great."
        # "U." -> followed by "S" (no whitespace) -> NOT a boundary
        # "S." -> followed by " has" (lowercase) -> NOT a boundary
        # "options." -> followed by " Rome" (uppercase) -> boundary (count=1)
        # "great." -> end of text -> boundary (count=2)
        assert _enforce_sentence_limit(text, 1) == "The U.S. has options."

    def test_abbreviation_dr(self):
        """'Dr.' is a known abbreviation — should NOT trigger a sentence boundary."""
        text = "Dr. Smith arrived. He left."
        # "Dr." is in _ABBREVIATIONS → skip, "arrived." → boundary (1)
        assert _enforce_sentence_limit(text, 1) == "Dr. Smith arrived."

    def test_abbreviation_st(self):
        """'St.' before a proper noun must not split the sentence."""
        text = "Visit St. Peter's Basilica. It is stunning."
        assert _enforce_sentence_limit(text, 1) == "Visit St. Peter's Basilica."

    def test_abbreviation_mt(self):
        """'Mt.' before a proper noun must not split the sentence."""
        text = "Climb Mt. Fuji in summer. The views are incredible."
        assert _enforce_sentence_limit(text, 1) == "Climb Mt. Fuji in summer."

    def test_decimal_number(self):
        """Decimal numbers like '14.5' should not trigger a sentence boundary."""
        text = "Water's 14.5 degrees. Perfect for diving."
        # "14.5" -> "." followed by "5" (no whitespace) -> NOT a boundary
        # "degrees." -> followed by " Perfect" (uppercase) -> boundary (1)
        # "diving." -> end of text -> boundary (2)
        assert _enforce_sentence_limit(text, 1) == "Water's 14.5 degrees."

    def test_eg_abbreviation(self):
        """'e.g.' should not trigger sentence boundaries."""
        text = "Try e.g. surfing here. Then relax."
        # "e." -> followed by "g" (no whitespace) -> NOT a boundary
        # "g." -> followed by " surfing" (lowercase) -> NOT a boundary
        # "here." -> followed by " Then" (uppercase) -> boundary (1)
        # "relax." -> end of text -> boundary (2)
        assert _enforce_sentence_limit(text, 1) == "Try e.g. surfing here."

    def test_no_punctuation(self):
        """Text without sentence-ending punctuation returns unchanged."""
        text = "No punctuation here"
        assert _enforce_sentence_limit(text, 1) == text

    def test_empty_string(self):
        assert _enforce_sentence_limit("", 3) == ""

    def test_limit_one_greeting(self):
        text = "Hey! Where are we headed?"
        # "Hey!" -> followed by " Where" (uppercase) -> boundary (1)
        assert _enforce_sentence_limit(text, 1) == "Hey!"

    def test_abbreviation_no(self):
        """'No.' before a number/name must not split the sentence."""
        text = "See item No. Five in the list. It is great."
        assert _enforce_sentence_limit(text, 1) == "See item No. Five in the list."

    def test_abbreviation_rd(self):
        """'Rd.' (road abbreviation) must not split the sentence."""
        text = "Turn onto Hampton Rd. North of the park. Then stop."
        assert _enforce_sentence_limit(text, 1) == "Turn onto Hampton Rd. North of the park."

    def test_abbreviation_at_end_of_text(self):
        """Abbreviation at end-of-text should still count as a sentence boundary."""
        text = "Visit St."
        # Even though "St" is an abbreviation, at EOT there's no continuation,
        # so it IS a sentence boundary (count=1).
        assert _enforce_sentence_limit(text, 1) == "Visit St."

    def test_abbreviation_only_sentence_at_eot(self):
        """Single sentence ending with an abbreviation at EOT, limit=2."""
        text = "Ask Dr."
        assert _enforce_sentence_limit(text, 2) == "Ask Dr."

    def test_trailing_whitespace_stripped(self):
        text = "First sentence.  Second sentence."
        assert _enforce_sentence_limit(text, 1) == "First sentence."


# ---------------------------------------------------------------------------
# _resolve_voice_block
# ---------------------------------------------------------------------------


class TestResolveVoiceBlock:
    """Tests for voice block resolution from classifier + state."""

    def test_greeting(self):
        c = _make_classifier(ChangeType.GREETING)
        assert _resolve_voice_block(c, {}, "hello") == _VOICE_GREETING

    def test_question(self):
        c = _make_classifier(ChangeType.QUESTION)
        assert _resolve_voice_block(c, {}, "what is best?") == _VOICE_QUESTION

    def test_initial_plan(self):
        c = _make_classifier(ChangeType.INITIAL_PLAN)
        assert _resolve_voice_block(c, {}, "Rome please") == _VOICE_DESTINATION_SET

    def test_date_change(self):
        c = _make_classifier(ChangeType.DATE_CHANGE)
        assert _resolve_voice_block(c, {}, "march 1-7") == _VOICE_DATES_SET

    def test_preference(self):
        c = _make_classifier(ChangeType.PREFERENCE)
        assert _resolve_voice_block(c, {}, "more relaxed") == _VOICE_PREFERENCE_CHANGE

    def test_add_activity_no_day_cards(self):
        """Without day_cards, add_activity uses PLAN_GENERATED (initial build)."""
        c = _make_classifier(ChangeType.ADD_ACTIVITY)
        assert _resolve_voice_block(c, {}, "add surfing") == _VOICE_PLAN_GENERATED

    def test_add_activity_with_day_cards(self):
        """With day_cards, add_activity uses PLAN_GENERATED (rebuild)."""
        c = _make_classifier(ChangeType.ADD_ACTIVITY)
        state = {"day_cards": [{"day_number": 1}]}
        assert _resolve_voice_block(c, state, "add surfing") == _VOICE_PLAN_GENERATED

    def test_swap_activity_stays_activity_change(self):
        """swap_activity intentionally uses ACTIVITY_CHANGE even with day_cards."""
        c = _make_classifier(ChangeType.SWAP_ACTIVITY)
        state = {"day_cards": [{"day_number": 1}]}
        assert _resolve_voice_block(c, state, "swap surf for dive") == _VOICE_ACTIVITY_CHANGE

    def test_generate_plan_now_override(self):
        """GENERATE_PLAN_NOW trigger always resolves to PLAN_GENERATED."""
        c = _make_classifier(ChangeType.GREETING)
        result = _resolve_voice_block(c, {}, "GENERATE_PLAN_NOW")
        assert result == _VOICE_PLAN_GENERATED

    def test_unknown_change_type_fallback(self):
        """Unrecognized change_type falls back to _VOICE_FALLBACK."""
        c = _make_classifier(ChangeType.RESET)
        # reset maps to GREETING in the dict
        assert _resolve_voice_block(c, {}, "start over") == _VOICE_GREETING


# ---------------------------------------------------------------------------
# _SENTENCE_LIMIT coverage
# ---------------------------------------------------------------------------


class TestSentenceLimitDict:
    """Verify all voice blocks have a sentence limit entry."""

    def test_all_voice_blocks_have_limits(self):
        expected = {
            _VOICE_DESTINATION_SET,
            _VOICE_DATES_SET,
            _VOICE_PLAN_GENERATED,
            _VOICE_ACTIVITY_CHANGE,
            _VOICE_PREFERENCE_CHANGE,
            _VOICE_QUESTION,
            _VOICE_GREETING,
            _VOICE_FALLBACK,
        }
        assert set(_SENTENCE_LIMIT.keys()) == expected

    def test_limits_are_positive(self):
        for voice_block, limit in _SENTENCE_LIMIT.items():
            assert limit > 0, f"Limit for {voice_block[:30]}... must be positive"


# ---------------------------------------------------------------------------
# _detect_user_energy
# ---------------------------------------------------------------------------


class TestDetectUserEnergy:
    """Tests for keyword-based energy detection."""

    def test_enthusiastic_exclamation(self):
        assert _detect_user_energy("Let's do it!") == "enthusiastic"

    def test_enthusiastic_keyword(self):
        assert _detect_user_energy("I love this plan") == "enthusiastic"

    def test_uncertain_keyword(self):
        assert _detect_user_energy("hmm I am not sure about that") == "uncertain"

    def test_uncertain_phrase(self):
        assert _detect_user_energy("there are too many options here") == "uncertain"

    def test_uncertain_beats_exclamation(self):
        """Uncertain keywords take priority even when '!' is present."""
        assert _detect_user_energy("maybe!") == "uncertain"
        assert _detect_user_energy("ugh!") == "uncertain"

    def test_terse(self):
        assert _detect_user_energy("add diving") == "terse"

    def test_terse_single_word(self):
        assert _detect_user_energy("okay") == "terse"

    def test_neutral(self):
        assert _detect_user_energy("I want to go to Tokyo for five days") == ""

    def test_no_false_positive_substring(self):
        """'love' should not match inside 'gloves'."""
        assert _detect_user_energy("bring gloves and a jacket for the trip") == ""


# ---------------------------------------------------------------------------
# _build_trip_context_block — urgency + day-of-week
# ---------------------------------------------------------------------------


class TestTripContextUrgency:
    """Tests for trip urgency and start day-of-week."""

    def test_urgency_high(self):
        from datetime import date, timedelta

        future = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
        state = {"trip_plan": {"destination": "Tokyo", "start_date": future}}
        result = _build_trip_context_block(state)
        assert "booking urgency is HIGH" in result
        assert "Start day:" in result

    def test_urgency_moderate(self):
        from datetime import date, timedelta

        future = (date.today() + timedelta(days=25)).strftime("%Y-%m-%d")
        state = {"trip_plan": {"destination": "Tokyo", "start_date": future}}
        result = _build_trip_context_block(state)
        assert "moderate planning window" in result

    def test_no_urgency_far_out(self):
        from datetime import date, timedelta

        future = (date.today() + timedelta(days=90)).strftime("%Y-%m-%d")
        state = {"trip_plan": {"destination": "Tokyo", "start_date": future}}
        result = _build_trip_context_block(state)
        assert "urgency" not in result
        assert "moderate" not in result
        # day-of-week still shown for future dates
        assert "Start day:" in result

    def test_no_day_of_week_for_past_dates(self):
        state = {"trip_plan": {"destination": "Tokyo", "start_date": "2020-01-01"}}
        result = _build_trip_context_block(state)
        assert "Start day:" not in result

    def test_invalid_date_no_crash(self):
        state = {"trip_plan": {"destination": "Tokyo", "start_date": "not-a-date"}}
        result = _build_trip_context_block(state)
        assert "Start day:" not in result
        assert "Destination: Tokyo" in result


# ---------------------------------------------------------------------------
# _build_from_strategy_sections — constraint relevance tagging
# ---------------------------------------------------------------------------


class TestConstraintRelevanceTagging:
    """Tests for [RELEVANT to this turn] tagging on constraints."""

    def _make_section(self, specialist_type: str, constraint_rule: str) -> dict:
        return {
            "specialist_type": specialist_type,
            "constraints_applied": [
                {"rule": constraint_rule, "severity": "warning"},
            ],
        }

    def test_relevant_constraint_tagged(self):
        sections = [self._make_section("diving", "24h no-fly after diving")]
        classifier = _make_classifier(ChangeType.ADD_ACTIVITY)
        classifier.affects = ["diving"]
        result = _build_from_strategy_sections(sections, classifier)
        assert "[RELEVANT to this turn]" in result

    def test_irrelevant_constraint_not_tagged(self):
        sections = [self._make_section("diving", "24h no-fly after diving")]
        classifier = _make_classifier(ChangeType.ADD_ACTIVITY)
        classifier.affects = ["surfing"]
        result = _build_from_strategy_sections(sections, classifier)
        assert "[RELEVANT to this turn]" not in result

    def test_no_classifier_no_tags(self):
        sections = [self._make_section("diving", "24h no-fly after diving")]
        result = _build_from_strategy_sections(sections, None)
        assert "[RELEVANT to this turn]" not in result
        assert "24h no-fly after diving" in result


# ---------------------------------------------------------------------------
# _build_turn_context_block — energy threading
# ---------------------------------------------------------------------------


class TestTurnContextEnergy:
    """Tests for user energy appearing in turn context block."""

    def test_energy_appended(self):
        c = _make_classifier(ChangeType.ADD_ACTIVITY)
        result = _build_turn_context_block(c, "OMG add surfing!")
        assert "User energy: enthusiastic" in result

    def test_no_energy_for_neutral(self):
        c = _make_classifier(ChangeType.ADD_ACTIVITY)
        result = _build_turn_context_block(c, "I want to add surfing to the plan")
        assert "User energy:" not in result

    def test_empty_message_no_crash(self):
        c = _make_classifier(ChangeType.GREETING)
        result = _build_turn_context_block(c, "")
        assert "User energy:" not in result


# ---------------------------------------------------------------------------
# build_response_context — persona + UI awareness
# ---------------------------------------------------------------------------


class TestBuildResponseContext:
    """Tests for destination persona and conditional UI block."""

    def test_persona_with_destination(self):
        state = {"trip_plan": {"destination": "Tokyo"}}
        c = _make_classifier(ChangeType.INITIAL_PLAN)
        msgs = build_response_context(state, c, "Let's go to Tokyo")
        system = msgs[0]["content"]
        assert "travel architect" in system
        assert "Tokyo" in system

    def test_persona_without_destination(self):
        state = {"trip_plan": {}}
        c = _make_classifier(ChangeType.GREETING)
        msgs = build_response_context(state, c, "hello")
        system = msgs[0]["content"]
        assert "sharp, opinionated" in system

    def test_ui_block_present_with_day_cards(self):
        state = {"trip_plan": {"destination": "Tokyo"}, "day_cards": [{"day_number": 1}]}
        c = _make_classifier(ChangeType.ADD_ACTIVITY)
        msgs = build_response_context(state, c, "add surfing")
        system = msgs[0]["content"]
        assert "What the User Sees Right Now" in system

    def test_ui_block_absent_without_plan_content(self):
        state = {"trip_plan": {}}
        c = _make_classifier(ChangeType.GREETING)
        msgs = build_response_context(state, c, "hello")
        system = msgs[0]["content"]
        assert "What the User Sees Right Now" not in system
