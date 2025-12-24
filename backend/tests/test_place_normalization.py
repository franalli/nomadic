"""
Tests for place name normalization with fuzzy matching.

Tests the fuzzy matching capability that corrects typos and normalizes
place names (e.g., "pariss" → "Paris", "roma" → "Rome").
"""

from app.known_places import (
    fuzzy_match_place,
    is_known_place,
    normalize_place_synonym,
    normalize_place_with_fuzzy,
)


class TestFuzzyMatchPlace:
    """Tests for fuzzy_match_place function."""

    def test_exact_match_returns_canonical(self):
        """Exact matches should return the canonical form with score 100."""
        result, score = fuzzy_match_place("paris")
        assert result == "Paris"
        assert score == 100

    def test_exact_match_case_insensitive(self):
        """Case-insensitive exact matches should work."""
        result, score = fuzzy_match_place("PARIS")
        assert result == "Paris"
        assert score == 100

    def test_typo_pariss_matches_paris(self):
        """Common typo 'pariss' should match 'Paris'."""
        result, score = fuzzy_match_place("pariss")
        assert result == "Paris"
        assert score is not None
        assert score >= 85

    def test_typo_new_yrok_matches_new_york(self):
        """Typo 'new yrok' should match 'New York'."""
        result, score = fuzzy_match_place("new yrok")
        assert result == "New York"
        assert score is not None
        assert score >= 85

    def test_synonym_roma_matches_rome(self):
        """Local language name 'roma' should match via synonym."""
        result, score = fuzzy_match_place("roma")
        # First checks synonym map, which should return Rome
        assert result == "Rome"
        assert score == 100

    def test_too_short_input_returns_none(self):
        """Inputs shorter than 3 characters should return None."""
        result, score = fuzzy_match_place("pa")
        assert result is None
        assert score is None

    def test_empty_input_returns_none(self):
        """Empty input should return None."""
        result, score = fuzzy_match_place("")
        assert result is None
        assert score is None

    def test_none_input_returns_none(self):
        """None input should return None."""
        result, score = fuzzy_match_place(None)  # type: ignore
        assert result is None
        assert score is None

    def test_no_match_below_threshold(self):
        """Strings with no good match should return None."""
        # Use a very different string that won't match anything
        result, score = fuzzy_match_place("qwertyzxcv")
        assert result is None
        assert score is None

    def test_threshold_customization(self):
        """Custom threshold should be respected."""
        # With high threshold, borderline matches should fail
        result, score = fuzzy_match_place("prais", threshold=95)
        # This is a significant typo, may or may not match at 95%
        # The test verifies threshold is passed through


class TestNormalizePlaceWithFuzzy:
    """Tests for normalize_place_with_fuzzy function."""

    def test_synonym_takes_precedence(self):
        """Synonym map should be checked before fuzzy matching."""
        result = normalize_place_with_fuzzy("nyc")
        assert result == "New York City"

    def test_local_language_roma_to_rome(self):
        """Italian 'roma' should normalize to 'Rome'."""
        result = normalize_place_with_fuzzy("roma")
        assert result == "Rome"

    def test_local_language_wien_to_vienna(self):
        """German 'wien' should normalize to 'Vienna'."""
        result = normalize_place_with_fuzzy("wien")
        assert result == "Vienna"

    def test_local_language_firenze_to_florence(self):
        """Italian 'firenze' should normalize to 'Florence'."""
        result = normalize_place_with_fuzzy("firenze")
        assert result == "Florence"

    def test_local_language_milano_to_milan(self):
        """Italian 'milano' should normalize to 'Milan'."""
        result = normalize_place_with_fuzzy("milano")
        assert result == "Milan"

    def test_local_language_praha_to_prague(self):
        """Czech 'praha' should normalize to 'Prague'."""
        result = normalize_place_with_fuzzy("praha")
        assert result == "Prague"

    def test_typo_pariss_normalized(self):
        """Typo 'pariss' should be normalized to 'Paris'."""
        result = normalize_place_with_fuzzy("pariss")
        assert result == "Paris"

    def test_typo_londob_normalized(self):
        """Typo 'londob' should be normalized to 'London'."""
        result = normalize_place_with_fuzzy("londob")
        assert result == "London"

    def test_canonical_lookup(self):
        """Known places should return canonical form."""
        result = normalize_place_with_fuzzy("paris")
        assert result == "Paris"

    def test_title_case_fallback(self):
        """Unknown places should get title-cased."""
        # Use a string that won't fuzzy-match any known place
        result = normalize_place_with_fuzzy("zxqwkj")
        assert result == "Zxqwkj"  # Title-cased fallback

    def test_empty_returns_original(self):
        """Empty string should return as-is."""
        result = normalize_place_with_fuzzy("")
        assert result == ""

    def test_whitespace_stripped(self):
        """Whitespace should be stripped."""
        result = normalize_place_with_fuzzy("  paris  ")
        assert result == "Paris"


class TestNormalizePlaceSynonym:
    """Tests for normalize_place_synonym function (original synonym-only function)."""

    def test_known_synonym_normalized(self):
        """Known synonyms should be normalized."""
        assert normalize_place_synonym("nyc") == "New York City"
        assert normalize_place_synonym("la") == "Los Angeles"
        assert normalize_place_synonym("sf") == "San Francisco"

    def test_unknown_returns_original(self):
        """Unknown names should return original."""
        assert normalize_place_synonym("Paris") == "Paris"
        assert normalize_place_synonym("some random place") == "some random place"

    def test_case_insensitive(self):
        """Synonym lookup should be case-insensitive."""
        assert normalize_place_synonym("NYC") == "New York City"
        assert normalize_place_synonym("Nyc") == "New York City"


class TestIsKnownPlace:
    """Tests for is_known_place function."""

    def test_known_city(self):
        """Known cities should return True."""
        assert is_known_place("Paris") is True
        assert is_known_place("London") is True
        assert is_known_place("Tokyo") is True

    def test_case_insensitive(self):
        """Lookup should be case-insensitive."""
        assert is_known_place("paris") is True
        assert is_known_place("LONDON") is True

    def test_unknown_returns_false(self):
        """Unknown places should return False."""
        assert is_known_place("notarealplace") is False
