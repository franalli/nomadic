#!/usr/bin/env python3
"""
P0 SSoT Violation Linter

Detects direct state mutations that should go through SSoT helper functions.

Usage:
    python scripts/check_ssot_violations.py [--fix] [files...]

Examples:
    cd backend && python scripts/check_ssot_violations.py app/planner/coordinator.py
    python backend/scripts/check_ssot_violations.py backend/app/planner/coordinator.py

Exit codes:
    0 - No violations found
    1 - Violations found (with --fix, means fixes were applied)
"""

import argparse
import re
import sys
from pathlib import Path
from typing import NamedTuple


class Violation(NamedTuple):
    """A detected SSoT violation."""

    file: str
    line_num: int
    line: str
    violation_type: str
    suggestion: str


# Patterns for SSoT violations
VIOLATION_PATTERNS = [
    {
        "name": "question_target_direct_assignment",
        "pattern": re.compile(r"^\s*state\.question_target\s*=\s*(.+)$"),
        "exception_function": "set_question_target",  # Allowed inside this function
        "suggestion": 'Use set_question_target(state, {value}, source="{context}")',
    },
    {
        "name": "metadata_question_target_direct",
        "pattern": re.compile(r"^\s*state\.metadata\[(['\"])question_target\1\]\s*=\s*(.+)$"),
        "exception_function": "set_question_target",  # Allowed inside this function
        "suggestion": 'Use set_question_target(state, {value}, source="{context}")',
    },
]

# Files/patterns to exclude
EXCLUDE_PATTERNS = [
    r".*test.*\.py$",  # Test files can have direct assignments
    r".*conftest\.py$",
]


def is_excluded(filepath: str) -> bool:
    """Check if file should be excluded from linting."""
    for pattern in EXCLUDE_PATTERNS:
        if re.match(pattern, filepath, re.IGNORECASE):
            return True
    return False


def resolve_input_path(file_arg: str) -> Path:
    """Resolve file arguments from either repo root or the backend directory."""
    filepath = Path(file_arg)
    if filepath.exists():
        return filepath

    backend_root = Path(__file__).resolve().parents[1]
    if file_arg.startswith("backend/"):
        repo_root_relative = backend_root.parent / file_arg
        if repo_root_relative.exists():
            return repo_root_relative

    backend_relative = backend_root / file_arg
    if backend_relative.exists():
        return backend_relative

    return filepath


def find_enclosing_function(lines: list[str], line_num: int) -> str:
    """Find the name of the function that encloses the given line number."""
    # Track indentation to find the function definition
    current_indent = len(lines[line_num - 1]) - len(lines[line_num - 1].lstrip())

    for j in range(line_num - 1, max(0, line_num - 100), -1):
        line = lines[j - 1] if j > 0 else ""
        # Check for function definition at same or lower indentation
        func_match = re.match(r"^(\s*)(?:async\s+)?def\s+(\w+)", line)
        if func_match:
            func_indent = len(func_match.group(1))
            # Function must be at lower indentation to be enclosing
            if func_indent < current_indent:
                return func_match.group(2)

    return "unknown"


def check_file(filepath: Path) -> list[Violation]:
    """Check a single file for SSoT violations."""
    violations = []

    try:
        content = filepath.read_text(encoding="utf-8")
    except Exception as e:
        print(f"Warning: Could not read {filepath}: {e}", file=sys.stderr)
        return violations

    lines = content.split("\n")

    for pattern_info in VIOLATION_PATTERNS:
        pattern = pattern_info["pattern"]
        exception_function = pattern_info.get("exception_function")

        for i, line in enumerate(lines, 1):
            match = pattern.match(line)
            if not match:
                continue

            # Find enclosing function
            enclosing_function = find_enclosing_function(lines, i)

            # Skip if inside exception function
            if exception_function and enclosing_function == exception_function:
                continue

            # Extract value for suggestion
            value = match.group(1) if match.groups() else "value"
            # Clean up the value (remove comments)
            if "#" in value:
                value = value[: value.index("#")].strip()

            suggestion = pattern_info["suggestion"].format(
                value=value.strip(),
                context=enclosing_function,
            )

            violations.append(
                Violation(
                    file=str(filepath),
                    line_num=i,
                    line=line.rstrip(),
                    violation_type=pattern_info["name"],
                    suggestion=suggestion,
                )
            )

    return violations


def main():
    parser = argparse.ArgumentParser(
        description="Check planner coordinator files for SSoT violations"
    )
    parser.add_argument(
        "files",
        nargs="*",
        default=["app/planner/coordinator.py"],
        help="Files to check (default: app/planner/coordinator.py)",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Attempt to auto-fix violations (not implemented yet)",
    )

    args = parser.parse_args()

    all_violations = []
    missing_files = []

    for file_arg in args.files:
        filepath = resolve_input_path(file_arg)

        if not filepath.exists():
            print(f"Error: File not found: {filepath}", file=sys.stderr)
            missing_files.append(str(filepath))
            continue

        if is_excluded(str(filepath)):
            continue

        violations = check_file(filepath)
        all_violations.extend(violations)

    if missing_files:
        print("\n[ERROR] Missing file(s):")
        for missing_file in missing_files:
            print(f"  {missing_file}")
        return 1

    if not all_violations:
        print("[OK] No SSoT violations found")
        return 0

    # Group by file
    by_file: dict[str, list[Violation]] = {}
    for v in all_violations:
        by_file.setdefault(v.file, []).append(v)

    print(f"\n[ERROR] Found {len(all_violations)} SSoT violation(s):\n")

    for file, violations in by_file.items():
        print(f"  {file}:")
        for v in sorted(violations, key=lambda x: x.line_num):
            print(f"    Line {v.line_num}: {v.violation_type}")
            print(f"      {v.line.strip()}")
            print(f"      FIX: {v.suggestion}")
            print()

    if args.fix:
        print("Note: --fix is not yet implemented. Manual fixes required.")

    return 1


if __name__ == "__main__":
    sys.exit(main())
