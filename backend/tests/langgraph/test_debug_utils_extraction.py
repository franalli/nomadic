"""
PR-E: Debug Utilities Extraction Tests

Verifies that debug logging utilities have been correctly extracted
from plan_graph.py to debug_utils.py while maintaining backwards
compatibility.
"""


class TestDebugUtilitiesExtraction:
    """Verify debug utilities are accessible from both modules."""

    def test_debug_importable_from_debug_utils(self):
        """_debug should be importable from debug_utils."""
        from app.debug_utils import _debug

        # Should not raise
        _debug("test message")

    def test_debug_importable_from_plan_graph(self):
        """_debug should still be importable from plan_graph (backwards compat)."""
        from app.plan_graph import _debug

        # Should not raise
        _debug("test message")

    def test_debug_error_importable_from_debug_utils(self):
        """_debug_error should be importable from debug_utils."""
        from app.debug_utils import _debug_error

        # Should not raise
        _debug_error("test error")

    def test_debug_error_importable_from_plan_graph(self):
        """_debug_error should still be importable from plan_graph."""
        from app.plan_graph import _debug_error

        # Should not raise
        _debug_error("test error")

    def test_debug_suggestions_importable(self):
        """_debug_suggestions should be importable from debug_utils."""
        from app.debug_utils import _debug_suggestions

        # Should not raise
        _debug_suggestions(["suggestion 1", "suggestion 2"], source="test")

    def test_safe_debug_importable(self):
        """safe_debug should be importable from debug_utils."""
        from app.debug_utils import safe_debug

        # Should not raise
        safe_debug("test safe debug")

    def test_safe_debug_error_importable(self):
        """safe_debug_error should be importable from debug_utils."""
        from app.debug_utils import safe_debug_error

        # Should not raise
        safe_debug_error("test safe error")

    def test_is_debug_enabled_function(self):
        """is_debug_enabled should return a boolean."""
        from app.debug_utils import is_debug_enabled

        result = is_debug_enabled()
        assert isinstance(result, bool)

    def test_plan_graph_imports_from_debug_utils(self):
        """Verify plan_graph imports debug utilities from debug_utils."""
        from app import debug_utils, plan_graph

        # Both should reference the same function
        assert plan_graph._debug is debug_utils._debug
        assert plan_graph._debug_error is debug_utils._debug_error
        assert plan_graph.safe_debug is debug_utils.safe_debug


class TestDebugFunctionality:
    """Verify debug functions work correctly after extraction."""

    def test_debug_non_fatal_with_exception(self):
        """_debug should handle exceptions gracefully."""
        from app.debug_utils import _debug

        # Should not raise even with problematic kwargs
        class BadRepr:
            def __repr__(self):
                raise RuntimeError("repr failed")

            def __str__(self):
                raise RuntimeError("str failed")

        _debug("test", bad_obj=BadRepr())  # Should not raise

    def test_debug_error_non_fatal_with_exception(self):
        """_debug_error should handle exceptions gracefully."""
        from app.debug_utils import _debug_error

        class BadRepr:
            def __repr__(self):
                raise RuntimeError("repr failed")

            def __str__(self):
                raise RuntimeError("str failed")

        _debug_error("test", bad_obj=BadRepr())  # Should not raise

    def test_safe_debug_absolutely_non_fatal(self):
        """safe_debug should never raise under any circumstance."""
        from app.debug_utils import safe_debug

        # Even with None as message - should not raise
        safe_debug(None)  # type: ignore

    def test_safe_debug_error_absolutely_non_fatal(self):
        """safe_debug_error should never raise under any circumstance."""
        from app.debug_utils import safe_debug_error

        safe_debug_error(None)  # type: ignore

    def test_debug_suggestions_empty_list(self):
        """_debug_suggestions should handle empty list."""
        from app.debug_utils import _debug_suggestions

        # Should not raise
        _debug_suggestions([])

    def test_debug_suggestions_with_source(self):
        """_debug_suggestions should include source in output."""
        from app.debug_utils import _debug_suggestions

        # Should not raise
        _debug_suggestions(["test"], source="test_source")

    def test_debug_truncates_long_message(self):
        """_debug should truncate very long messages."""
        from app.debug_utils import _debug

        long_message = "x" * 5000
        # Should not raise
        _debug(long_message)

    def test_debug_truncates_long_kwargs(self):
        """_debug should truncate very long kwargs values."""
        from app.debug_utils import _debug

        long_value = "y" * 500
        # Should not raise
        _debug("test", long_kwarg=long_value)
