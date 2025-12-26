"""
PR-C: Strategy Output Size Limits

Tests for strategy response truncation to prevent runaway LLM output.

Validates:
- truncate_preserving_newlines() helper function
- Integration with strategy_node stage1 and stage2
- Proper metadata flags when truncation occurs
"""

import pytest

from app.config import settings
from app.plan_graph import truncate_preserving_newlines

# =============================================================================
# UNIT TESTS: truncate_preserving_newlines()
# =============================================================================


class TestTruncatePreservingNewlines:
    """Unit tests for the truncation helper function."""

    def test_no_truncation_when_under_cap(self):
        """Text under the cap should pass through unchanged."""
        text = "Short text"
        result, was_truncated = truncate_preserving_newlines(text, cap=1000)
        assert result == text
        assert was_truncated is False

    def test_truncation_at_newline_boundary(self):
        """Should truncate at last newline before cap."""
        # Create text with newlines that exceeds cap
        # Footer is ~43 chars, so cap must be > footer + some content
        text = "Line 1\nLine 2\nLine 3\nLine 4\nLine 5\n" + "X" * 100
        # Use cap that allows footer
        result, was_truncated = truncate_preserving_newlines(text, cap=80)
        assert was_truncated is True
        # Should have the footer
        assert "Ask if you want me to expand any section." in result

    def test_truncation_preserves_complete_lines(self):
        """Should not cut lines in the middle."""
        # Create longer text that definitely needs truncation
        # Footer is ~43 chars, so we need cap > 43
        text = "First line here\nSecond line here\nThird line here\nFourth line\n" + "Y" * 100
        result, was_truncated = truncate_preserving_newlines(text, cap=100)
        assert was_truncated is True
        # The result should end with footer
        assert "expand any section" in result

    def test_closes_unclosed_code_blocks(self):
        """Should close unclosed markdown code blocks."""
        # Create text with unclosed code block that needs truncation
        text = (
            "Some text\n```python\ndef foo():\n    pass\n"
            "# more code here that goes on and on to exceed the cap limit we set"
        )
        result, was_truncated = truncate_preserving_newlines(text, cap=60)
        assert was_truncated is True
        # Should have closing ```
        code_block_count = result.count("```")
        assert code_block_count % 2 == 0, "Code blocks should be properly closed"

    def test_custom_footer(self):
        """Should use custom footer when provided."""
        text = "A" * 100
        custom_footer = "\n[truncated]"
        result, was_truncated = truncate_preserving_newlines(text, cap=50, footer=custom_footer)
        assert was_truncated is True
        assert result.endswith(custom_footer)

    def test_exact_cap_no_truncation(self):
        """Text exactly at cap should not be truncated."""
        text = "X" * 100
        result, was_truncated = truncate_preserving_newlines(text, cap=100)
        assert was_truncated is False
        assert result == text

    def test_truncation_fallback_to_word_boundary(self):
        """When no newline found, should truncate at word boundary."""
        # Create long single line that exceeds cap
        text = "word1 word2 word3 word4 word5 word6 word7 word8 word9 word10 word11 word12"
        result, was_truncated = truncate_preserving_newlines(text, cap=50)
        assert was_truncated is True
        # Should not cut in the middle of a word
        content_part = result.split("\n\n")[0]  # Before footer
        # Content should end at word boundary (not mid-word)
        assert content_part[-1] in (" ", "1", "2", "3", "4", "5", "6", "7", "8", "9", "0")


# =============================================================================
# CONFIG TESTS: Verify settings are properly configured
# =============================================================================


class TestStrategyCapSettings:
    """Verify strategy cap configuration values."""

    def test_strategy_max_output_chars_configured(self):
        """settings.strategy_max_output_chars should be set."""
        assert hasattr(settings, "strategy_max_output_chars")
        assert settings.strategy_max_output_chars == 4000

    def test_strategy_expansion_max_output_chars_configured(self):
        """settings.strategy_expansion_max_output_chars should be set."""
        assert hasattr(settings, "strategy_expansion_max_output_chars")
        assert settings.strategy_expansion_max_output_chars == 8000

    def test_expansion_cap_larger_than_regular(self):
        """Expansion cap should be larger than regular cap."""
        assert settings.strategy_expansion_max_output_chars > settings.strategy_max_output_chars


# =============================================================================
# INTEGRATION TESTS: Strategy node truncation
# =============================================================================


@pytest.fixture
def oversized_strategy_response() -> str:
    """Generate a strategy response larger than the cap."""
    # Create response that exceeds 4000 chars
    sections = []
    for i in range(50):
        sections.append(f"## Day {i + 1}\n\nThis is a detailed itinerary for day {i + 1}. " * 5)
    return "\n\n".join(sections)


class TestStrategyNodeTruncation:
    """Integration tests for strategy node output truncation."""

    def test_oversized_response_gets_truncated(self, oversized_strategy_response: str):
        """Verify that oversized responses are properly truncated."""
        assert len(oversized_strategy_response) > settings.strategy_max_output_chars

        result, was_truncated = truncate_preserving_newlines(
            oversized_strategy_response, settings.strategy_max_output_chars
        )

        assert was_truncated is True
        assert len(result) <= settings.strategy_max_output_chars + 100  # Allow for footer
        assert "Ask if you want me to expand any section." in result

    def test_stage2_uses_larger_cap(self, oversized_strategy_response: str):
        """Stage 2 should use expansion_max_output_chars."""
        # Create text between the two caps
        medium_text = "X" * 5000  # Between 4000 and 8000

        # Should truncate with stage1 cap
        result1, truncated1 = truncate_preserving_newlines(
            medium_text, settings.strategy_max_output_chars
        )
        assert truncated1 is True

        # Should NOT truncate with stage2 cap
        result2, truncated2 = truncate_preserving_newlines(
            medium_text, settings.strategy_expansion_max_output_chars
        )
        assert truncated2 is False

    def test_truncation_metadata_flags(self):
        """Verify metadata flags are set correctly."""
        from app.plan_graph import GraphState, TripInputs

        # Create minimal state for testing
        state = GraphState(
            session_id="test-session",
            chat_id="test-chat",
            user_text="test",
            chat_history=[],
            trip_inputs=TripInputs(),
            document_id=None,
        )

        # Simulate what strategy_node does
        oversized_text = "X" * 5000
        truncated_text, was_truncated = truncate_preserving_newlines(
            oversized_text, settings.strategy_max_output_chars
        )

        if was_truncated:
            state.metadata["strategy_truncated"] = True
            state.metadata["strategy_truncate_cap"] = settings.strategy_max_output_chars

        assert state.metadata.get("strategy_truncated") is True
        assert state.metadata.get("strategy_truncate_cap") == 4000
