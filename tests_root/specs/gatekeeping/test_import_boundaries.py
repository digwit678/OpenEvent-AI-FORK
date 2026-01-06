"""
Guard test: Prevent runtime code from importing deprecated groups modules.

The `backend/workflows/groups/*` hierarchy is DEPRECATED and exists only for
backwards compatibility in tests. New code in `backend/` must import from
`backend/workflows/steps/*` instead.

This test fails if any Python file in `backend/` (excluding tests) imports
from `backend.workflows.groups.*`.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path
from typing import List, Tuple

import pytest

# Directories that are allowed to import from groups (for backwards compatibility testing)
ALLOWED_IMPORTERS = {
    "tests",
    "backend/tests",
    "_legacy",
}

# The deprecated module prefix we're guarding against
DEPRECATED_PREFIX = "backend.workflows.groups"


def _is_allowed_path(file_path: Path) -> bool:
    """Check if a file path is in an allowed directory."""
    path_str = str(file_path)
    return any(allowed in path_str for allowed in ALLOWED_IMPORTERS)


def _find_deprecated_imports(file_path: Path) -> List[Tuple[int, str]]:
    """
    Parse a Python file and find any imports from the deprecated groups module.

    Returns a list of (line_number, import_statement) tuples.
    """
    violations = []

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(file_path))
    except (SyntaxError, UnicodeDecodeError):
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(DEPRECATED_PREFIX):
                    violations.append((node.lineno, f"import {alias.name}"))

        elif isinstance(node, ast.ImportFrom):
            if node.module and node.module.startswith(DEPRECATED_PREFIX):
                names = ", ".join(alias.name for alias in node.names)
                violations.append((node.lineno, f"from {node.module} import {names}"))

    return violations


def _scan_backend_for_violations() -> List[Tuple[Path, int, str]]:
    """
    Scan all Python files in backend/ for deprecated imports.

    Returns a list of (file_path, line_number, import_statement) tuples.
    """
    backend_root = Path(__file__).parent.parent.parent.parent / "backend"
    all_violations = []

    for py_file in backend_root.rglob("*.py"):
        # Skip allowed directories
        if _is_allowed_path(py_file):
            continue

        # Skip the groups directory itself (it contains the re-exports)
        if "workflows/groups" in str(py_file):
            continue

        violations = _find_deprecated_imports(py_file)
        for line_no, import_stmt in violations:
            all_violations.append((py_file, line_no, import_stmt))

    return all_violations


@pytest.mark.v4
def test_no_runtime_imports_from_deprecated_groups():
    """
    Verify that no runtime code imports from workflows.groups.*.

    The groups hierarchy is DEPRECATED. All runtime imports must use
    backend.workflows.steps.* instead. This test enforces the boundary.
    """
    violations = _scan_backend_for_violations()

    if violations:
        msg_lines = [
            "",
            "=" * 70,
            "DEPRECATED IMPORT VIOLATION",
            "=" * 70,
            "",
            "The following files import from the deprecated 'backend.workflows.groups' module.",
            "Please update these imports to use 'backend.workflows.steps' instead:",
            "",
        ]

        for file_path, line_no, import_stmt in sorted(violations):
            rel_path = file_path.relative_to(Path(__file__).parent.parent.parent.parent)
            msg_lines.append(f"  {rel_path}:{line_no}")
            msg_lines.append(f"    {import_stmt}")
            msg_lines.append("")

        msg_lines.extend([
            "=" * 70,
            "Migration guide:",
            "  - backend.workflows.groups.intake → backend.workflows.steps.step1_intake",
            "  - backend.workflows.groups.date_confirmation → backend.workflows.steps.step2_date_confirmation",
            "  - backend.workflows.groups.room_availability → backend.workflows.steps.step3_room_availability",
            "  - backend.workflows.groups.offer → backend.workflows.steps.step4_offer",
            "  - backend.workflows.groups.negotiation_close → backend.workflows.steps.step5_negotiation",
            "  - backend.workflows.groups.transition → backend.workflows.steps.step6_transition",
            "  - backend.workflows.groups.event_confirmation → backend.workflows.steps.step7_confirmation",
            "=" * 70,
        ])

        pytest.fail("\n".join(msg_lines))


@pytest.mark.v4
def test_groups_modules_are_pure_reexports():
    """
    Verify that all Python files in groups/ are pure re-exports (no function definitions
    without DEPRECATED docstring).
    """
    groups_root = Path(__file__).parent.parent.parent.parent / "backend" / "workflows" / "groups"
    violations = []

    for py_file in groups_root.rglob("*.py"):
        if py_file.name == "__init__.py":
            continue

        try:
            source = py_file.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        # Check if file has function definitions
        if "\ndef " in source or source.startswith("def "):
            # Check if it has DEPRECATED marker
            if "DEPRECATED" not in source:
                violations.append(py_file)

    if violations:
        msg_lines = [
            "",
            "The following groups/ files have function definitions without DEPRECATED marker:",
            "",
        ]
        for v in sorted(violations):
            rel_path = v.relative_to(Path(__file__).parent.parent.parent.parent)
            msg_lines.append(f"  {rel_path}")
        msg_lines.append("")
        msg_lines.append("These files should be converted to pure re-exports from steps/.")

        pytest.fail("\n".join(msg_lines))
