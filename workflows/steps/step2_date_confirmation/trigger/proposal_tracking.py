"""
Proposal tracking utilities for Step2 Date Confirmation workflow.

Extracted from step2_handler.py for better modularity (D3 refactoring).

These functions manage the date proposal attempt counter and history,
preventing the system from repeatedly proposing the same dates.

Usage:
    from workflows.steps.step2_date_confirmation.trigger.proposal_tracking import (
        increment_date_attempt,
        collect_proposal_history,
        proposal_skip_dates,
        update_proposal_history,
        reset_date_attempts,
    )
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from workflows.io.database import update_event_metadata


# -----------------------------------------------------------------------------
# Attempt Counter
# -----------------------------------------------------------------------------


def increment_date_attempt(event_entry: Dict[str, Any]) -> int:
    """
    Increment and persist the count of date proposal attempts.

    Returns the updated attempt count.
    """
    try:
        current = int(event_entry.get("date_proposal_attempts") or 0)
    except (TypeError, ValueError):
        current = 0
    updated = current + 1
    event_entry["date_proposal_attempts"] = updated
    update_event_metadata(event_entry, date_proposal_attempts=updated)
    return updated


def reset_date_attempts(event_entry: Dict[str, Any]) -> None:
    """Clear attempt counters after a successful confirmation."""
    event_entry["date_proposal_attempts"] = 0
    event_entry.pop("date_proposal_history", None)
    update_event_metadata(
        event_entry,
        date_proposal_attempts=0,
        date_proposal_history=[],
    )


# -----------------------------------------------------------------------------
# Proposal History
# -----------------------------------------------------------------------------


def collect_proposal_history(event_entry: Dict[str, Any]) -> List[str]:
    """
    Retrieve the list of previously proposed dates.

    Returns a list of ISO date strings that have been proposed.
    """
    history = event_entry.get("date_proposal_history")
    if isinstance(history, list):
        return [str(entry) for entry in history if entry]
    return []


def proposal_skip_dates(
    event_entry: Dict[str, Any],
    attempt: int,
    extra: Optional[Sequence[str]] = None,
) -> set[str]:
    """
    Get dates to skip when generating new proposals.

    On attempt > 1, includes previously proposed dates from history.
    Also includes any extra dates passed in.
    """
    skip: set[str] = set()
    if extra:
        skip.update(str(value) for value in extra if value)
    if attempt > 1:
        skip.update(collect_proposal_history(event_entry))
    return skip


def update_proposal_history(
    event_entry: Dict[str, Any],
    iso_dates: Sequence[str],
) -> List[str]:
    """
    Append new dates to the proposal history.

    Returns the updated history list.
    """
    history = collect_proposal_history(event_entry)
    for iso_value in iso_dates:
        if iso_value and iso_value not in history:
            history.append(iso_value)
    event_entry["date_proposal_history"] = history
    update_event_metadata(event_entry, date_proposal_history=list(history))
    return history


# -----------------------------------------------------------------------------
# Exports
# -----------------------------------------------------------------------------

__all__ = [
    "increment_date_attempt",
    "reset_date_attempts",
    "collect_proposal_history",
    "proposal_skip_dates",
    "update_proposal_history",
]
