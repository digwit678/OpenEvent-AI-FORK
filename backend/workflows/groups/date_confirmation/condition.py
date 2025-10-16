"""Condition helpers for the date confirmation workflow group."""

from __future__ import annotations

from workflows.conditions.checks import is_valid_ddmmyyyy as _is_valid_ddmmyyyy

__workflow_role__ = "Condition"


def is_valid_ddmmyyyy(value: str | None) -> bool:
    """[Condition] Validate that a string follows the DD.MM.YYYY format."""

    return _is_valid_ddmmyyyy(value)

