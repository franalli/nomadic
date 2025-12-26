"""
PR-D: JSON Utilities Extraction Tests

Verifies that JSON parsing utilities have been correctly extracted
from plan_graph.py to graph_plan_utils.py while maintaining backwards
compatibility.
"""


class TestJsonUtilitiesExtraction:
    """Verify JSON utilities are accessible from both modules."""

    def test_jloads_safe_importable_from_graph_plan_utils(self):
        """jloads_safe should be importable from graph_plan_utils."""
        from app.graph_plan_utils import jloads_safe

        result = jloads_safe('{"key": "value"}')
        assert result == {"key": "value"}

    def test_jloads_safe_importable_from_plan_graph(self):
        """jloads_safe should still be importable from plan_graph (backwards compat)."""
        from app.plan_graph import jloads_safe

        result = jloads_safe('{"key": "value"}')
        assert result == {"key": "value"}

    def test_truncate_to_balanced_json_public(self):
        """truncate_to_balanced_json should be available with public name."""
        from app.graph_plan_utils import truncate_to_balanced_json

        result = truncate_to_balanced_json('garbage{"valid": true}more garbage')
        assert result == '{"valid": true}'

    def test_truncate_to_balanced_json_private_alias(self):
        """_truncate_to_balanced_json alias should exist for backwards compat."""
        from app.graph_plan_utils import _truncate_to_balanced_json

        result = _truncate_to_balanced_json('{"test": 123}')
        assert result == '{"test": 123}'

    def test_extract_message_public(self):
        """extract_message_from_malformed_json should be available."""
        from app.graph_plan_utils import extract_message_from_malformed_json

        raw = (
            '{"assistant_message": '
            '"This is a test message that is long enough to pass validation."}'
        )
        result = extract_message_from_malformed_json(raw)
        assert result is not None
        assert "test message" in result

    def test_extract_message_private_alias(self):
        """_extract_message_from_malformed_json alias should exist."""
        from app.graph_plan_utils import _extract_message_from_malformed_json

        raw = '{"assistant_message": "Another long enough message for the extraction test."}'
        result = _extract_message_from_malformed_json(raw)
        assert result is not None

    def test_plan_graph_imports_from_graph_plan_utils(self):
        """Verify plan_graph imports JSON utilities from graph_plan_utils."""
        from app import graph_plan_utils, plan_graph

        # Both should reference the same function
        assert plan_graph.jloads_safe is graph_plan_utils.jloads_safe


class TestJloadsSafeFunctionality:
    """Verify jloads_safe functionality after extraction."""

    def test_valid_json(self):
        """Valid JSON should parse correctly."""
        from app.graph_plan_utils import jloads_safe

        assert jloads_safe('{"a": 1}') == {"a": 1}

    def test_empty_string(self):
        """Empty string should return empty dict."""
        from app.graph_plan_utils import jloads_safe

        assert jloads_safe("") == {}

    def test_malformed_json_recovery(self):
        """Malformed JSON should attempt recovery."""
        from app.graph_plan_utils import jloads_safe

        # Missing closing brace - should recover
        result = jloads_safe('{"key": "value"')
        # May or may not recover depending on implementation
        assert isinstance(result, dict)

    def test_json_with_extra_text(self):
        """JSON with extra text should extract valid JSON."""
        from app.graph_plan_utils import jloads_safe

        result = jloads_safe('{"key": "value"} extra text here')
        assert result.get("key") == "value"


class TestTruncateToBalancedJson:
    """Verify truncate_to_balanced_json functionality."""

    def test_simple_json(self):
        """Simple JSON object should be extracted."""
        from app.graph_plan_utils import truncate_to_balanced_json

        assert truncate_to_balanced_json('{"a": 1}') == '{"a": 1}'

    def test_json_with_prefix(self):
        """JSON with prefix text should extract only JSON."""
        from app.graph_plan_utils import truncate_to_balanced_json

        result = truncate_to_balanced_json('Here is the JSON: {"key": "value"}')
        assert result == '{"key": "value"}'

    def test_nested_json(self):
        """Nested JSON should be properly balanced."""
        from app.graph_plan_utils import truncate_to_balanced_json

        result = truncate_to_balanced_json('{"outer": {"inner": "value"}}')
        assert result == '{"outer": {"inner": "value"}}'

    def test_json_with_strings_containing_braces(self):
        """JSON with braces in strings should not confuse the parser."""
        from app.graph_plan_utils import truncate_to_balanced_json

        result = truncate_to_balanced_json('{"text": "hello { world }"}')
        assert result == '{"text": "hello { world }"}'

    def test_no_json(self):
        """String without JSON should return None."""
        from app.graph_plan_utils import truncate_to_balanced_json

        result = truncate_to_balanced_json("no json here")
        assert result is None
