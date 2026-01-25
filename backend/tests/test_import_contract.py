# backend/tests/test_import_contract.py
"""
Import contract enforcement tests.

Verifies that the planner facade exports expected V2 symbols.
"""

import re
from pathlib import Path

import pytest

# Patterns that indicate direct plan_graph imports
BANNED_IMPORT_PATTERNS = [
    r"from\s+app\.plan_graph\s+import",
    r"from\s+\.\.?plan_graph\s+import",
    r"import\s+app\.plan_graph",
]

# Directories/files allowed to import directly from plan_graph_v2
ALLOWLIST_PATHS = [
    # The planner package itself can import from plan_graph_v2
    "backend/app/planner/",
    # Tests can import directly (for now)
    "backend/tests/",
    "tests/",
]


def get_backend_root() -> Path:
    """Get the backend directory root."""
    return Path(__file__).parent.parent


def is_allowed_path(file_path: Path, backend_root: Path) -> bool:
    """Check if a file path is in the allowlist."""
    rel_path = str(file_path.relative_to(backend_root.parent)).replace("\\", "/")

    for allowed in ALLOWLIST_PATHS:
        if rel_path.startswith(allowed) or f"/{allowed}" in f"/{rel_path}":
            return True

    return False


def find_python_files(root: Path, exclude_dirs: set = None) -> list:
    """Find all Python files in a directory tree."""
    exclude_dirs = exclude_dirs or {"__pycache__", ".venv", "venv", "node_modules"}
    python_files = []

    for path in root.rglob("*.py"):
        if any(ex in path.parts for ex in exclude_dirs):
            continue
        python_files.append(path)

    return python_files


def check_file_for_banned_imports(file_path: Path, patterns: list) -> list:
    """Check a file for banned import patterns."""
    violations = []

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return []

    for line_num, line in enumerate(content.splitlines(), start=1):
        for pattern in patterns:
            if re.search(pattern, line):
                violations.append(
                    {
                        "file": str(file_path),
                        "line": line_num,
                        "content": line.strip(),
                        "pattern": pattern,
                    }
                )

    return violations


class TestImportContract:
    """Test that import contract is enforced."""

    def test_no_direct_plan_graph_imports_outside_allowlist(self):
        """No file outside the allowlist should import directly from plan_graph.py."""
        backend_root = get_backend_root()
        app_root = backend_root / "app"

        if not app_root.exists():
            pytest.skip("app directory not found")

        violations = []

        for py_file in find_python_files(app_root):
            if is_allowed_path(py_file, backend_root):
                continue

            # Skip plan_graph files themselves
            if "plan_graph" in py_file.name:
                continue

            file_violations = check_file_for_banned_imports(py_file, BANNED_IMPORT_PATTERNS)
            violations.extend(file_violations)

        if violations:
            violation_msg = "\n".join(
                f"  {v['file']}:{v['line']}: {v['content']}" for v in violations
            )
            pytest.fail(
                f"Found {len(violations)} direct plan_graph.py import(s) "
                f"outside allowlist:\n{violation_msg}\n\n"
                "Use 'from app.planner import ...' instead."
            )

    def test_main_py_uses_planner_facade(self):
        """main.py should import from app.planner, not app.plan_graph directly."""
        backend_root = get_backend_root()
        main_py = backend_root / "app" / "main.py"

        if not main_py.exists():
            pytest.skip("main.py not found")

        content = main_py.read_text(encoding="utf-8")

        for pattern in BANNED_IMPORT_PATTERNS:
            match = re.search(pattern, content)
            if match:
                line_num = content[: match.start()].count("\n") + 1
                line_content = content.splitlines()[line_num - 1].strip()

                pytest.fail(
                    f"main.py imports directly from plan_graph.py:\n"
                    f"  Line {line_num}: {line_content}\n\n"
                    "Use 'from app.planner import ...' instead."
                )


class TestPlannerFacadeExports:
    """Test that the planner facade exports expected symbols."""

    def test_facade_imports_successfully(self):
        """The planner facade should import without errors."""
        from app import planner

        assert planner is not None

    def test_facade_exports_run_turn(self):
        """run_turn should be exported from facade."""
        from app.planner import run_turn

        assert callable(run_turn)

    def test_facade_exports_run_turn_streaming(self):
        """run_turn_streaming should be exported from facade."""
        from app.planner import run_turn_streaming

        assert run_turn_streaming is not None

    def test_facade_exports_graph_state(self):
        """GraphState should be exported from facade."""
        from app.planner import GraphState

        assert GraphState is not None

    def test_facade_exports_trip_inputs(self):
        """TripInputs should be exported from facade."""
        from app.planner import TripInputs

        assert TripInputs is not None

    def test_facade_exports_debug_info(self):
        """get_planner_debug_info should be exported from facade."""
        from app.planner import get_planner_debug_info

        assert callable(get_planner_debug_info)

    def test_facade_exports_meta_helpers(self):
        """Metadata helpers should be exported from facade."""
        from app.planner import (
            init_turn_metadata,
            meta_append,
            meta_get,
            meta_increment,
            meta_set,
            meta_set_once,
        )

        assert callable(init_turn_metadata)
        assert callable(meta_get)
        assert callable(meta_set)
        assert callable(meta_set_once)
        assert callable(meta_append)
        assert callable(meta_increment)

    def test_facade_exports_test_mode_helpers(self):
        """Test mode helpers should be exported from facade."""
        from app.planner import is_test_mode, raise_if_test_mode

        assert callable(is_test_mode)
        assert callable(raise_if_test_mode)

    def test_facade_exports_cache_helpers(self):
        """Cache helpers should be exported from facade."""
        from app.planner import (
            cache_delete,
            cache_get,
            cache_set,
        )

        assert callable(cache_get)
        assert callable(cache_set)
        assert callable(cache_delete)

    def test_facade_exports_v2_state_models(self):
        """V2 state models should be exported from facade."""
        from app.planner import (
            GraphStateV2,
            ItineraryBlock,
            SpecialistConstraint,
            TripPlan,
        )

        assert GraphStateV2 is not None
        assert TripPlan is not None
        assert ItineraryBlock is not None
        assert SpecialistConstraint is not None

    def test_facade_all_exports(self):
        """__all__ should contain all expected exports."""
        from app import planner

        expected_exports = [
            "run_turn",
            "run_turn_streaming",
            "GraphState",
            "TripInputs",
            "get_planner_debug_info",
            "meta_get",
            "meta_set",
            "is_test_mode",
            "cache_get",
            # V2 state models
            "GraphStateV2",
            "TripPlan",
        ]

        for export in expected_exports:
            assert export in planner.__all__, f"{export} not in __all__"
            assert hasattr(planner, export), f"{export} not accessible on module"
