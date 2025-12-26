# backend/tests/test_hash_ban.py
"""
Test that bans Python's built-in hash() in planner code.

PR5: Stable hashing utilities - enforces use of stable_hash* functions
instead of Python's built-in hash() which is non-deterministic across processes.

Why this matters:
- Python's hash() uses PYTHONHASHSEED which is randomized by default
- Cache keys using hash() will differ between test runs and processes
- This causes flaky tests and non-reproducible cache behavior

Allowed alternatives:
- stable_hash() for string hashes
- stable_hash_int() for integer hashes (cohort assignment)
- stable_hash_index() for list indexing
"""

import re
from pathlib import Path
from typing import List, Tuple

import pytest

# Pattern to detect hash() usage that's not part of a longer identifier
# Matches: hash(, but not _hash(, compute_hash(, etc.
HASH_PATTERN = re.compile(r"(?<![_a-zA-Z])hash\(")

# Files in planner package that should use stable_hash
PLANNER_PATHS = [
    "backend/app/plan_graph.py",
    "backend/app/planner/",
    "backend/app/pattern_matching.py",
    "backend/app/graph_plan_utils.py",
]

# Specific lines that are allowed to use hash() with justification
ALLOWLIST = [
    # _compute_prompt_bundle_hash uses hashlib, not hash()
    # The function name contains "hash" but doesn't call hash()
    # _hash_value has a fallback that uses hash() for non-serializable types
    # This is acceptable as a last resort fallback
    ("backend/app/plan_graph.py", "_hash_value", "Fallback for non-JSON-serializable types"),
]


def get_backend_root() -> Path:
    """Get the backend directory root."""
    # This file is at backend/tests/test_hash_ban.py
    return Path(__file__).parent.parent


def find_hash_usages(file_path: Path) -> List[Tuple[int, str]]:
    """
    Find all lines in a file that use hash().

    Returns list of (line_number, line_content) tuples.
    """
    violations = []

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return []

    for line_num, line in enumerate(content.splitlines(), start=1):
        # Skip comments
        stripped = line.lstrip()
        if stripped.startswith("#"):
            continue

        # Check for hash( pattern
        if HASH_PATTERN.search(line):
            violations.append((line_num, line.strip()))

    return violations


def is_allowed(file_path: str, line_content: str) -> bool:
    """Check if a specific hash() usage is in the allowlist."""
    for allowed_file, allowed_context, _reason in ALLOWLIST:
        if allowed_file in file_path and allowed_context in line_content:
            return True
    return False


class TestHashBan:
    """Tests that enforce the hash() ban in planner code."""

    def test_no_hash_in_plan_graph(self):
        """
        plan_graph.py should not use hash() except in allowlisted locations.

        Use stable_hash(), stable_hash_int(), or stable_hash_index() instead.
        """
        backend_root = get_backend_root()
        plan_graph = backend_root / "app" / "plan_graph.py"

        if not plan_graph.exists():
            pytest.skip("plan_graph.py not found")

        violations = find_hash_usages(plan_graph)

        # Filter out allowlisted usages
        actual_violations = [
            (line_num, line)
            for line_num, line in violations
            if not is_allowed(str(plan_graph), line)
        ]

        if actual_violations:
            msg_lines = [
                f"Found {len(actual_violations)} banned hash() usage(s) in plan_graph.py:",
            ]
            for line_num, line in actual_violations:
                msg_lines.append(f"  Line {line_num}: {line}")
            msg_lines.append("")
            msg_lines.append(
                "Use stable_hash(), stable_hash_int(), or stable_hash_index() instead."
            )
            msg_lines.append("See app/planner/hashing.py for stable alternatives.")

            pytest.fail("\n".join(msg_lines))

    def test_no_hash_in_planner_package(self):
        """
        Planner package modules should not use hash().

        Exception: hashing.py itself (which provides stable alternatives).
        """
        backend_root = get_backend_root()
        planner_dir = backend_root / "app" / "planner"

        if not planner_dir.exists():
            pytest.skip("planner directory not found")

        violations = []

        for py_file in planner_dir.glob("*.py"):
            # Skip hashing.py itself
            if py_file.name == "hashing.py":
                continue

            file_violations = find_hash_usages(py_file)
            for line_num, line in file_violations:
                if not is_allowed(str(py_file), line):
                    violations.append((py_file.name, line_num, line))

        if violations:
            msg_lines = [
                f"Found {len(violations)} banned hash() usage(s) in planner package:",
            ]
            for filename, line_num, line in violations:
                msg_lines.append(f"  {filename}:{line_num}: {line}")
            msg_lines.append("")
            msg_lines.append(
                "Use stable_hash(), stable_hash_int(), or stable_hash_index() instead."
            )

            pytest.fail("\n".join(msg_lines))

    def test_no_hash_in_pattern_matching(self):
        """
        pattern_matching.py should not use hash().
        """
        backend_root = get_backend_root()
        pattern_file = backend_root / "app" / "pattern_matching.py"

        if not pattern_file.exists():
            pytest.skip("pattern_matching.py not found")

        violations = find_hash_usages(pattern_file)

        if violations:
            msg_lines = [
                f"Found {len(violations)} banned hash() usage(s) in pattern_matching.py:",
            ]
            for line_num, line in violations:
                msg_lines.append(f"  Line {line_num}: {line}")
            msg_lines.append("")
            msg_lines.append("Use stable_hash() functions instead.")

            pytest.fail("\n".join(msg_lines))

    def test_no_hash_in_graph_plan_utils(self):
        """
        graph_plan_utils.py should not use hash().
        """
        backend_root = get_backend_root()
        utils_file = backend_root / "app" / "graph_plan_utils.py"

        if not utils_file.exists():
            pytest.skip("graph_plan_utils.py not found")

        violations = find_hash_usages(utils_file)

        if violations:
            msg_lines = [
                f"Found {len(violations)} banned hash() usage(s) in graph_plan_utils.py:",
            ]
            for line_num, line in violations:
                msg_lines.append(f"  Line {line_num}: {line}")
            msg_lines.append("")
            msg_lines.append("Use stable_hash() functions instead.")

            pytest.fail("\n".join(msg_lines))


class TestAllowlist:
    """Tests for the allowlist entries."""

    def test_allowlist_entries_still_exist(self):
        """
        Verify that allowlisted hash() usages still exist.

        If an allowlisted usage is removed, the allowlist entry should be removed too.
        """
        backend_root = get_backend_root()

        for allowed_file, allowed_context, _reason in ALLOWLIST:
            file_path = backend_root.parent / allowed_file

            if not file_path.exists():
                pytest.fail(f"Allowlisted file not found: {allowed_file}")

            content = file_path.read_text(encoding="utf-8")

            if allowed_context not in content:
                pytest.fail(
                    f"Allowlisted context '{allowed_context}' not found in {allowed_file}. "
                    f"Remove this allowlist entry if the code was refactored."
                )
