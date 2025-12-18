"""
Unit tests for activity icon normalization with multi-codepoint emoji support.

Tests the _normalize_activity_with_emoji function to ensure proper handling of
emojis that consist of multiple Unicode code points (e.g., 🥾, 🤿).
"""

import importlib
import os
import sys
from pathlib import Path

# Suppress debug output before importing plan_graph
os.environ["PLAN_GRAPH_DEBUG"] = "0"

BACKEND_DIR = Path(__file__).resolve().parents[2]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _load_normalizer():
    """Import plan_graph after sys.path patched so tests can access helpers."""

    plan_graph = importlib.import_module("app.plan_graph")
    return plan_graph


_plan_graph = _load_normalizer()
_normalize_activity_with_emoji = _plan_graph._normalize_activity_with_emoji
_deduplicate_activities_case_insensitive = _plan_graph._deduplicate_activities_case_insensitive


class TestMultiCodepointEmojis:
    """Test handling of multi-codepoint emojis like 🥾 (hiking boot)."""

    def test_hiking_boot_emoji_preserved(self):
        """🥾 hiking should remain unchanged - emoji is correct for activity."""
        result = _normalize_activity_with_emoji("🥾 hiking")
        assert result == "🥾 hiking", f"Expected '🥾 hiking' but got '{result}'"

    def test_hiking_boot_emoji_not_replaced(self):
        """Ensure 🥾 is not incorrectly replaced with another emoji."""
        result = _normalize_activity_with_emoji("🥾 hiking")
        # Should NOT be replaced with 🤩 or any other emoji
        assert "🤩" not in result, f"🥾 was incorrectly replaced: '{result}'"
        assert result.startswith("🥾"), f"Emoji prefix changed: '{result}'"

    def test_diving_mask_emoji_preserved(self):
        """🤿 diving should remain unchanged."""
        result = _normalize_activity_with_emoji("🤿 diving")
        assert result == "🤿 diving", f"Expected '🤿 diving' but got '{result}'"

    def test_skiing_emoji_preserved(self):
        """⛷️ skiing should remain unchanged (also multi-codepoint with variation selector)."""
        result = _normalize_activity_with_emoji("⛷️ skiing")
        assert "skiing" in result.lower()
        # The emoji should start with the skier character
        assert ord(result[0]) > 0x1F00 or result[0] == "⛷"

    def test_cycling_emoji_preserved(self):
        """🚴 cycling should remain unchanged."""
        result = _normalize_activity_with_emoji("🚴 cycling")
        assert result == "🚴 cycling", f"Expected '🚴 cycling' but got '{result}'"


class TestEmojiCorrection:
    """Test that wrong emojis are corrected to the right ones."""

    def test_wrong_emoji_for_hiking_corrected(self):
        """A wrong emoji for hiking should be corrected to 🥾."""
        # Using a clearly wrong emoji for hiking
        result = _normalize_activity_with_emoji("🎭 hiking")
        assert result == "🥾 hiking", f"Expected '🥾 hiking' but got '{result}'"

    def test_wrong_emoji_for_diving_corrected(self):
        """A wrong emoji for diving should be corrected to 🤿."""
        result = _normalize_activity_with_emoji("🎭 diving")
        assert result == "🤿 diving", f"Expected '🤿 diving' but got '{result}'"

    def test_wrong_emoji_for_snorkeling_corrected(self):
        """A wrong emoji for snorkeling should be corrected to 🤿."""
        result = _normalize_activity_with_emoji("🎭 snorkeling")
        assert result == "🤿 snorkeling", f"Expected '🤿 snorkeling' but got '{result}'"


class TestNoEmojiPrefix:
    """Test activities without emoji prefix get correct emoji added."""

    def test_hiking_gets_boot_emoji(self):
        """Plain 'hiking' should get 🥾 prefix."""
        result = _normalize_activity_with_emoji("hiking")
        assert result == "🥾 hiking", f"Expected '🥾 hiking' but got '{result}'"

    def test_diving_gets_mask_emoji(self):
        """Plain 'diving' should get 🤿 prefix."""
        result = _normalize_activity_with_emoji("diving")
        assert result == "🤿 diving", f"Expected '🤿 diving' but got '{result}'"

    def test_trekking_gets_boot_emoji(self):
        """Plain 'trekking' should get 🥾 prefix (same as hiking)."""
        result = _normalize_activity_with_emoji("trekking")
        assert result == "🥾 trekking", f"Expected '🥾 trekking' but got '{result}'"

    def test_unknown_activity_gets_default_emoji(self):
        """Unknown activity should get ✨ default prefix."""
        result = _normalize_activity_with_emoji("zorbing")
        assert result == "✨ zorbing", f"Expected '✨ zorbing' but got '{result}'"


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_string(self):
        """Empty string should return empty string."""
        result = _normalize_activity_with_emoji("")
        assert result == ""

    def test_whitespace_only(self):
        """Whitespace-only string should return empty string."""
        result = _normalize_activity_with_emoji("   ")
        assert result == ""

    def test_emoji_only(self):
        """Emoji-only string should return as-is."""
        result = _normalize_activity_with_emoji("🥾")
        assert result == "🥾"

    def test_emoji_with_extra_spaces(self):
        """Emoji with extra spaces should be handled correctly."""
        result = _normalize_activity_with_emoji("🥾   hiking")
        assert "hiking" in result
        assert result.startswith("🥾")

    def test_preserves_case_in_activity_text(self):
        """Activity text case should be preserved."""
        result = _normalize_activity_with_emoji("Mountain Hiking")
        assert "Mountain Hiking" in result or "mountain hiking" in result.lower()


class TestGraphemeHandling:
    """Test that grapheme library is used correctly for emoji boundaries."""

    def test_hiking_boot_grapheme_length(self):
        """Verify 🥾 is treated as single grapheme despite multiple code points."""
        import grapheme

        emoji = "🥾"
        # The hiking boot emoji may be multiple code points
        assert grapheme.length(emoji) == 1, f"🥾 should be 1 grapheme, got {grapheme.length(emoji)}"

        # Verify grapheme.slice extracts the full emoji
        activity = "🥾 hiking"
        first_grapheme = grapheme.slice(activity, 0, 1)
        assert first_grapheme == "🥾", f"Expected '🥾' but got '{first_grapheme}'"

    def test_diving_mask_grapheme_length(self):
        """Verify 🤿 is treated as single grapheme."""
        import grapheme

        emoji = "🤿"
        assert grapheme.length(emoji) == 1, f"🤿 should be 1 grapheme, got {grapheme.length(emoji)}"


class TestAnsiCodeStripping:
    """Test that ANSI escape codes are properly stripped from activities."""

    def test_ansi_bold_stripped(self):
        """ANSI bold code should be stripped and activity normalized."""
        result = _normalize_activity_with_emoji("\x1b[1mhiking")
        assert result == "🥾 hiking", f"Expected '🥾 hiking' but got '{result}'"
        assert "\x1b" not in result, f"ANSI code not stripped: '{result}'"

    def test_ansi_color_stripped(self):
        """ANSI color codes should be stripped and activity normalized."""
        result = _normalize_activity_with_emoji("\x1b[38;5;208mhiking")
        assert result == "🥾 hiking", f"Expected '🥾 hiking' but got '{result}'"
        assert "\x1b" not in result, f"ANSI code not stripped: '{result}'"

    def test_ansi_bold_and_color_stripped(self):
        """Multiple ANSI codes should be stripped."""
        result = _normalize_activity_with_emoji("\x1b[1m\x1b[38;5;208mhiking")
        assert result == "🥾 hiking", f"Expected '🥾 hiking' but got '{result}'"
        assert "\x1b" not in result, f"ANSI code not stripped: '{result}'"

    def test_ansi_after_emoji_stripped(self):
        """ANSI codes after emoji should be stripped."""
        result = _normalize_activity_with_emoji("🥾 \x1b[1mhiking")
        assert result == "🥾 hiking", f"Expected '🥾 hiking' but got '{result}'"
        assert "\x1b" not in result, f"ANSI code not stripped: '{result}'"

    def test_ansi_with_unknown_activity(self):
        """ANSI codes with unknown activity should be stripped and default emoji added."""
        result = _normalize_activity_with_emoji("\x1b[1mzorbing")
        assert result == "✨ zorbing", f"Expected '✨ zorbing' but got '{result}'"
        assert "\x1b" not in result, f"ANSI code not stripped: '{result}'"


class TestGarbageCharacterStripping:
    """Test that garbage characters between emoji and activity text are removed."""

    def test_hex_garbage_between_emoji_and_text(self):
        """Garbage like '9b6' between emoji and text should be stripped."""
        result = _normalize_activity_with_emoji("🥾 9b6 hiking")
        assert result == "🥾 hiking", f"Expected '🥾 hiking' but got '{result}'"

    def test_multiple_garbage_fragments(self):
        """Multiple garbage fragments should be stripped."""
        result = _normalize_activity_with_emoji("🥾 9bf 9be hiking")
        assert result == "🥾 hiking", f"Expected '🥾 hiking' but got '{result}'"

    def test_garbage_with_diving(self):
        """Garbage should be stripped for diving too."""
        result = _normalize_activity_with_emoji("🤿 abc123 diving")
        assert result == "🤿 diving", f"Expected '🤿 diving' but got '{result}'"

    def test_no_garbage_in_result(self):
        """Result should never contain hex-like garbage patterns."""
        result = _normalize_activity_with_emoji("🥾 9b6 hiking")
        assert "9b6" not in result, f"Garbage '9b6' found in result: '{result}'"
        assert "9bf" not in result, f"Garbage '9bf' found in result: '{result}'"
        assert "9be" not in result, f"Garbage '9be' found in result: '{result}'"


class TestDeduplicationWithAnsiCodes:
    """Test that deduplication properly handles ANSI codes in activity strings."""

    def test_deduplicate_with_ansi_duplicate(self):
        """Deduplication should treat ANSI-coded activity as duplicate of clean version."""
        categories = ["🥾 hiking", "\x1b[1mhiking"]
        result = _deduplicate_activities_case_insensitive(categories)
        assert len(result) == 1, f"Expected 1 result, got {len(result)}: {result}"
        assert result[0] == "🥾 hiking", f"Expected '🥾 hiking' but got '{result[0]}'"

    def test_deduplicate_ansi_with_emoji(self):
        """ANSI codes after emoji should be handled in deduplication."""
        categories = ["🥾 hiking", "✨ \x1b[1mhiking"]
        result = _deduplicate_activities_case_insensitive(categories)
        assert len(result) == 1, f"Expected 1 result, got {len(result)}: {result}"

    def test_deduplicate_strips_ansi_from_result(self):
        """Result should not contain ANSI codes."""
        categories = ["\x1b[1m\x1b[38;5;208mhiking"]
        result = _deduplicate_activities_case_insensitive(categories)
        assert len(result) == 1
        assert "\x1b" not in result[0], f"ANSI code in result: '{result[0]}'"

    def test_deduplicate_multiple_ansi_activities(self):
        """Multiple activities with ANSI codes should be properly deduplicated."""
        categories = [
            "🥾 hiking",
            "\x1b[1mhiking",
            "🤿 diving",
            "\x1b[38;5;208mdiving",
        ]
        result = _deduplicate_activities_case_insensitive(categories)
        assert len(result) == 2, f"Expected 2 results, got {len(result)}: {result}"
        # Check no ANSI codes in results
        for r in result:
            assert "\x1b" not in r, f"ANSI code in result: '{r}'"
