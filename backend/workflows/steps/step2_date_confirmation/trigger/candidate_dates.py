"""
Step 2 Candidate Date Generation - Sub-handlers for date option collection.

Extracted from step2_handler.py as part of D7 refactoring (Dec 2025).

This module contains the core logic for generating candidate dates:
- Week scope collection
- Fuzzy Friday matching
- Date suggestion integration
- Weekday prioritization
- Message and action building

The main `_present_candidate_dates()` in step2_handler.py orchestrates these functions.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from backend.workflows.common.datetime_parse import (
    build_window_iso,
    parse_first_date,
    to_iso_date,
)
from backend.workflows.common.prompts import verbalize_draft_body
from backend.workflows.common.timeutils import format_iso_date_to_ddmmyyyy
from backend.workflows.common.types import WorkflowState
from backend.debug.hooks import trace_db_read
from backend.services.availability import next_five_venue_dates
from backend.workflows.steps.step1_intake.condition.checks import suggest_dates

from .constants import (
    WEEKDAY_LABELS as _WEEKDAY_LABELS,
    MONTH_NAME_TO_INDEX as _MONTH_NAME_TO_INDEX,
)
from backend.utils.dates import MONTH_INDEX_TO_NAME, from_hints
from .date_parsing import (
    iso_date_is_past as _iso_date_is_past,
    safe_parse_iso_date as _safe_parse_iso_date,
    format_display_dates as _format_display_dates,
    human_join as _human_join,
    parse_weekday_mentions as _parse_weekday_mentions,
    weekday_indices_from_hint as _weekday_indices_from_hint,
    clean_weekdays_hint as _clean_weekdays_hint,
)
from .calendar_checks import (
    candidate_is_calendar_free as _candidate_is_calendar_free,
    maybe_fuzzy_friday_candidates as _maybe_fuzzy_friday_candidates,
)
from .proposal_tracking import (
    proposal_skip_dates as _proposal_skip_dates,
)
from .window_helpers import (
    _reference_date_from_state,
    _resolve_window_hints,
    _has_window_constraints,
    _candidate_dates_for_constraints,
    _extract_participants_from_state,
)
from .step2_utils import (
    _normalize_time_value,
    _to_time,
    _format_label_text,
    _date_header_label,
    _format_day_list,
    _weekday_label_from_dates,
    _month_label_from_dates,
    _pluralize_weekday_hint,
    _preface_with_apology,
    _window_payload,
    _clear_invalid_weekdays_hint,
    _is_weekend_token,
)
from .types import ConfirmationWindow


# =============================================================================
# WEEKDAY ALTERNATIVES (moved from step2_handler.py to avoid circular imports)
# =============================================================================

def _collect_preferred_weekday_alternatives(
    *,
    start_from: date,
    preferred_weekdays: Sequence[int],
    preferred_room: Optional[str],
    start_time: Optional[time],
    end_time: Optional[time],
    skip_dates: Sequence[str],
    existing: Set[str],
    limit: int,
) -> List[str]:
    """Find additional dates matching preferred weekdays.

    Scans forward from start_from, looking for dates that:
    - Match one of the preferred weekday indices
    - Are not in the skip set or already seen
    - Pass calendar availability checks

    Returns:
        List of ISO date strings matching the weekday preference.
    """
    if not preferred_weekdays:
        return []
    if limit <= 0:
        return []
    skip_lookup = set(skip_dates or [])
    skip_lookup.update(existing)
    results: List[str] = []
    max_days = max(90, limit * 14)
    for offset in range(max_days):
        candidate = start_from + timedelta(days=offset)
        weekday_idx = candidate.weekday()
        if weekday_idx not in preferred_weekdays:
            continue
        iso_value = candidate.isoformat()
        if iso_value in skip_lookup:
            continue
        if _iso_date_is_past(iso_value):
            continue
        if not _candidate_is_calendar_free(preferred_room, iso_value, start_time, end_time):
            skip_lookup.add(iso_value)
            continue
        results.append(iso_value)
        skip_lookup.add(iso_value)
        if len(results) >= limit:
            break
    return results


# =============================================================================
# CANDIDATE COLLECTION
# =============================================================================

def collect_candidates_from_week_scope(
    week_scope: Optional[Dict[str, Any]],
    *,
    skip_set: Set[str],
    min_requested_date: Optional[date],
    preferred_room: str,
    start_time_obj: Optional[time],
    end_time_obj: Optional[time],
) -> Tuple[List[str], Set[str], Set[str]]:
    """Collect candidate dates from week scope.

    Returns:
        Tuple of (formatted_dates, seen_iso, busy_skipped)
    """
    formatted_dates: List[str] = []
    seen_iso: Set[str] = set()
    busy_skipped: Set[str] = set()

    if not week_scope:
        return formatted_dates, seen_iso, busy_skipped

    for iso_value in week_scope.get("dates", []):
        if (
            not iso_value
            or iso_value in seen_iso
            or iso_value in skip_set
            or _iso_date_is_past(iso_value)
        ):
            continue
        candidate_dt = _safe_parse_iso_date(iso_value)
        if min_requested_date and candidate_dt and candidate_dt < min_requested_date:
            continue
        if not _candidate_is_calendar_free(preferred_room, iso_value, start_time_obj, end_time_obj):
            busy_skipped.add(iso_value)
            continue
        seen_iso.add(iso_value)
        formatted_dates.append(iso_value)

    return formatted_dates, seen_iso, busy_skipped


def collect_candidates_from_fuzzy(
    fuzzy_candidates: List[str],
    *,
    skip_set: Set[str],
    seen_iso: Set[str],
    min_requested_date: Optional[date],
    preferred_room: str,
    start_time_obj: Optional[time],
    end_time_obj: Optional[time],
) -> Tuple[List[str], Set[str], Set[str]]:
    """Collect candidate dates from fuzzy Friday matching.

    Returns:
        Tuple of (new_dates, updated_seen_iso, busy_skipped)
    """
    formatted_dates: List[str] = []
    busy_skipped: Set[str] = set()

    for iso_value in fuzzy_candidates:
        if (
            not iso_value
            or iso_value in seen_iso
            or iso_value in skip_set
            or _iso_date_is_past(iso_value)
        ):
            continue
        candidate_dt = _safe_parse_iso_date(iso_value)
        if min_requested_date and candidate_dt and candidate_dt < min_requested_date:
            continue
        if not _candidate_is_calendar_free(preferred_room, iso_value, start_time_obj, end_time_obj):
            busy_skipped.add(iso_value)
            continue
        seen_iso.add(iso_value)
        formatted_dates.append(iso_value)

    return formatted_dates, seen_iso, busy_skipped


def collect_candidates_from_constraints(
    state: WorkflowState,
    user_info: Dict[str, Any],
    event_entry: Dict[str, Any],
    *,
    attempt: int,
    limit: int,
    skip_set: Set[str],
    seen_iso: Set[str],
    min_requested_date: Optional[date],
    preferred_room: str,
    start_time_obj: Optional[time],
    end_time_obj: Optional[time],
) -> Tuple[List[str], Set[str], Set[str]]:
    """Collect candidate dates from window constraints.

    Returns:
        Tuple of (new_dates, updated_seen_iso, busy_skipped)
    """
    formatted_dates: List[str] = []
    busy_skipped: Set[str] = set()

    constraints_for_window = {
        "vague_month": user_info.get("vague_month") or event_entry.get("vague_month"),
        "weekday": user_info.get("vague_weekday") or event_entry.get("vague_weekday"),
        "time_of_day": user_info.get("vague_time_of_day") or event_entry.get("vague_time_of_day"),
    }
    window_hints = _resolve_window_hints(constraints_for_window, state)
    strict_window = _has_window_constraints(window_hints)

    if strict_window:
        hinted_dates = _candidate_dates_for_constraints(
            state,
            constraints_for_window,
            limit=limit,
            window_hints=window_hints,
            strict=attempt == 1,
        )
        for iso_value in hinted_dates:
            if (
                not iso_value
                or iso_value in seen_iso
                or iso_value in skip_set
                or _iso_date_is_past(iso_value)
            ):
                continue
            candidate_dt = _safe_parse_iso_date(iso_value)
            if min_requested_date and candidate_dt and candidate_dt < min_requested_date:
                continue
            if not _candidate_is_calendar_free(preferred_room, iso_value, start_time_obj, end_time_obj):
                busy_skipped.add(iso_value)
                continue
            seen_iso.add(iso_value)
            formatted_dates.append(iso_value)

    return formatted_dates, seen_iso, busy_skipped


def collect_candidates_from_suggestions(
    state: WorkflowState,
    thread_id: str,
    anchor_dt: Optional[datetime],
    *,
    attempt: int,
    skip_set: Set[str],
    seen_iso: Set[str],
    min_requested_date: Optional[date],
    preferred_room: str,
    start_time_obj: Optional[time],
    end_time_obj: Optional[time],
    collection_cap: int,
) -> Tuple[List[str], Set[str], Set[str]]:
    """Collect candidate dates from suggest_dates and supplemental sources.

    Returns:
        Tuple of (new_dates, updated_seen_iso, busy_skipped)
    """
    formatted_dates: List[str] = []
    busy_skipped: Set[str] = set()

    days_ahead = min(180, 45 + (attempt - 1) * 30)
    max_results = 5 if attempt <= 2 else 7

    candidate_dates_ddmmyyyy: List[str] = suggest_dates(
        state.db,
        preferred_room=preferred_room,
        start_from_iso=anchor_dt.isoformat() if anchor_dt else state.message.ts,
        days_ahead=days_ahead,
        max_results=max_results,
    )
    trace_db_read(
        thread_id,
        "Step2_Date",
        "db.dates.next5",
        {
            "preferred_room": preferred_room,
            "anchor": anchor_dt.isoformat() if anchor_dt else state.message.ts,
            "result_count": len(candidate_dates_ddmmyyyy),
            "days_ahead": days_ahead,
        },
    )

    for raw in candidate_dates_ddmmyyyy:
        iso_value = to_iso_date(raw)
        if not iso_value:
            continue
        if (
            _iso_date_is_past(iso_value)
            or iso_value in seen_iso
            or iso_value in skip_set
        ):
            continue
        candidate_dt = _safe_parse_iso_date(iso_value)
        if min_requested_date and candidate_dt and candidate_dt < min_requested_date:
            continue
        if not _candidate_is_calendar_free(preferred_room, iso_value, start_time_obj, end_time_obj):
            busy_skipped.add(iso_value)
            continue
        seen_iso.add(iso_value)
        formatted_dates.append(iso_value)

    return formatted_dates, seen_iso, busy_skipped


def collect_supplemental_candidates(
    thread_id: str,
    anchor_dt: Optional[datetime],
    *,
    limit: int,
    attempt: int,
    skip_set: Set[str],
    seen_iso: Set[str],
    busy_skipped: Set[str],
    min_requested_date: Optional[date],
    preferred_room: str,
    start_time_obj: Optional[time],
    end_time_obj: Optional[time],
    collection_cap: int,
    days_ahead: int,
) -> Tuple[List[str], Set[str], Set[str]]:
    """Collect supplemental candidates when initial collection falls short.

    Returns:
        Tuple of (new_dates, updated_seen_iso, updated_busy_skipped)
    """
    formatted_dates: List[str] = []

    skip_dates_for_next = {_safe_parse_iso_date(iso) for iso in seen_iso.union(skip_set)}
    supplemental = next_five_venue_dates(
        anchor_dt,
        skip_dates={dt for dt in skip_dates_for_next if dt is not None},
        count=max(limit * 2, 10 if attempt > 1 else 5),
    )
    trace_db_read(
        thread_id,
        "Step2_Date",
        "db.dates.next5",
        {
            "preferred_room": preferred_room,
            "anchor": anchor_dt.isoformat() if anchor_dt else None,
            "result_count": len(supplemental),
            "days_ahead": days_ahead,
        },
    )

    for candidate in supplemental:
        iso_candidate = candidate if isinstance(candidate, str) else candidate.isoformat()
        if (
            iso_candidate in seen_iso
            or iso_candidate in skip_set
            or _iso_date_is_past(iso_candidate)
        ):
            continue
        candidate_dt = _safe_parse_iso_date(iso_candidate)
        if min_requested_date and candidate_dt and candidate_dt < min_requested_date:
            continue
        if not _candidate_is_calendar_free(preferred_room, iso_candidate, start_time_obj, end_time_obj):
            busy_skipped.add(iso_candidate)
            continue
        seen_iso.add(iso_candidate)
        formatted_dates.append(iso_candidate)
        if len(formatted_dates) >= collection_cap:
            break

    return formatted_dates, seen_iso, busy_skipped


# =============================================================================
# WEEKDAY PRIORITIZATION
# =============================================================================

def prioritize_by_weekday(
    formatted_dates: List[str],
    preferred_weekdays: Set[int],
    *,
    preferred_weekday_list: List[int],
    min_requested_date: Optional[date],
    reference_day: date,
    preferred_room: str,
    start_time_obj: Optional[time],
    end_time_obj: Optional[time],
    skip_set: Set[str],
    busy_skipped: Set[str],
    seen_iso: Set[str],
    collection_cap: int,
) -> Tuple[List[str], List[str], bool]:
    """Prioritize dates by preferred weekdays.

    Returns:
        Tuple of (prioritized_dates, prioritized_list, weekday_shortfall)
    """
    # Uses _collect_preferred_weekday_alternatives from this module (no circular import)

    prioritized_dates: List[str] = []
    weekday_shortfall = False

    if not preferred_weekdays:
        formatted_dates = sorted(formatted_dates)
        return formatted_dates, list(formatted_dates), weekday_shortfall

    weekday_cache: Dict[str, Optional[int]] = {}

    def _weekday_for(iso_value: str) -> Optional[int]:
        if iso_value not in weekday_cache:
            parsed = _safe_parse_iso_date(iso_value)
            weekday_cache[iso_value] = parsed.weekday() if parsed else None
        return weekday_cache[iso_value]

    formatted_dates = sorted(
        formatted_dates,
        key=lambda iso: (
            0 if (_weekday_for(iso) in preferred_weekdays) else 1,
            iso,
        ),
    )
    prioritized_matches = [iso for iso in formatted_dates if _weekday_for(iso) in preferred_weekdays]
    prioritized_rest = [iso for iso in formatted_dates if _weekday_for(iso) not in preferred_weekdays]

    if not prioritized_matches:
        supplemental_matches = _collect_preferred_weekday_alternatives(
            start_from=min_requested_date or reference_day,
            preferred_weekdays=preferred_weekday_list,
            preferred_room=preferred_room,
            start_time=start_time_obj,
            end_time=end_time_obj,
            skip_dates=skip_set.union(busy_skipped),
            existing=seen_iso,
            limit=collection_cap,
        )
        if supplemental_matches:
            for iso_value in supplemental_matches:
                if iso_value in seen_iso:
                    continue
                seen_iso.add(iso_value)
                formatted_dates.append(iso_value)
            formatted_dates = sorted(
                formatted_dates,
                key=lambda iso: (
                    0 if (_weekday_for(iso) in preferred_weekdays) else 1,
                    iso,
                ),
            )
            prioritized_matches = [iso for iso in formatted_dates if _weekday_for(iso) in preferred_weekdays]
            prioritized_rest = [iso for iso in formatted_dates if _weekday_for(iso) not in preferred_weekdays]

    if prioritized_matches:
        formatted_dates = prioritized_matches
        prioritized_dates = prioritized_matches
    else:
        formatted_dates = prioritized_rest
        prioritized_dates = prioritized_rest
        weekday_shortfall = bool(formatted_dates)

    return formatted_dates, prioritized_dates, weekday_shortfall


# =============================================================================
# ACTION PAYLOAD BUILDING
# =============================================================================

def build_table_and_actions(
    formatted_dates: List[str],
    time_display: str,
    limit: int = 5,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build table rows and action payloads for candidate dates.

    Returns:
        Tuple of (table_rows, actions_payload)
    """
    table_rows: List[Dict[str, Any]] = []
    actions_payload: List[Dict[str, Any]] = []

    for iso_value in formatted_dates[:limit]:
        display_date = format_iso_date_to_ddmmyyyy(iso_value) or iso_value
        table_rows.append({
            "iso_date": iso_value,
            "display_date": display_date,
            "time_of_day": time_display,
        })
        actions_payload.append({
            "type": "select_date",
            "label": f"{display_date} ({time_display})",
            "date": iso_value,
            "display_date": display_date,
        })

    return table_rows, actions_payload


def build_draft_message(
    body_markdown: str,
    formatted_dates: List[str],
    table_rows: List[Dict[str, Any]],
    actions_payload: List[Dict[str, Any]],
    headers: List[str],
    label_base: str,
    escalate_to_hil: bool,
) -> Dict[str, Any]:
    """Build the draft message payload for candidate dates.

    Returns:
        Draft message dictionary
    """
    thread_state_label = "Waiting on HIL" if escalate_to_hil else "Awaiting Client Response"

    draft_message = {
        "body": body_markdown,
        "body_markdown": body_markdown,
        "step": 2,
        "next_step": "Room Availability",
        "topic": "date_candidates",
        "candidate_dates": [format_iso_date_to_ddmmyyyy(iso) or iso for iso in formatted_dates[:5]],
        "table_blocks": [
            {
                "type": "dates",
                "label": label_base,
                "rows": table_rows,
            }
        ] if table_rows else [],
        "actions": actions_payload,
        "headers": headers,
        "thread_state": thread_state_label,
        "requires_approval": escalate_to_hil,
    }

    if escalate_to_hil:
        draft_message["hil_reason"] = "Client can't find suitable date, needs manual help"

    return draft_message


# =============================================================================
# WEEK SCOPE RESOLUTION (D10)
# =============================================================================

def resolve_week_scope(
    user_info: Dict[str, Any],
    event_entry: Dict[str, Any],
    reference_day: date,
) -> Optional[Dict[str, Any]]:
    """Resolve week scope from user hints and event data.

    Extracted from step2_handler.py as part of D10 refactoring.

    NOTE: This function modifies event_entry via _clear_invalid_weekdays_hint.
    Consider calling the cleanup separately if you need a pure function.

    Args:
        user_info: Current user information dict
        event_entry: Event entry dict (may be modified)
        reference_day: Reference date for relative date calculation

    Returns:
        Dict with dates, week_index, month_label, label, weekdays_hint
        or None if no valid week scope can be resolved.
    """
    _clear_invalid_weekdays_hint(event_entry)

    window_scope: Dict[str, Any] = {}
    for candidate in (event_entry.get("window_scope"), user_info.get("window")):
        if isinstance(candidate, dict):
            window_scope.update(candidate)

    month_hint = (
        window_scope.get("month")
        or user_info.get("vague_month")
        or event_entry.get("vague_month")
    )
    week_index = (
        window_scope.get("week_index")
        or user_info.get("week_index")
        or event_entry.get("week_index")
    )
    weekdays_hint_raw = (
        window_scope.get("weekdays_hint")
        or user_info.get("weekdays_hint")
        or event_entry.get("weekdays_hint")
    )
    weekdays_hint = _clean_weekdays_hint(weekdays_hint_raw)
    weekday_token = (
        window_scope.get("weekday")
        or user_info.get("vague_weekday")
        or event_entry.get("vague_weekday")
    )

    if not month_hint or (week_index is None and not weekdays_hint):
        return None

    include_weekends = _is_weekend_token(weekday_token)
    dates = from_hints(
        month=month_hint,
        week_index=week_index,
        weekdays_hint=weekdays_hint if isinstance(weekdays_hint, (list, tuple, set)) else None,
        reference=reference_day,
        mon_fri_only=not include_weekends,
    )
    if not dates:
        return None

    try:
        first_day = datetime.fromisoformat(dates[0])
    except ValueError:
        return None

    derived_week_index = ((first_day.day - 1) // 7) + 1
    month_index = _MONTH_NAME_TO_INDEX.get(str(month_hint).strip().lower())
    if month_index is None:
        month_index = first_day.month
    month_label = window_scope.get("month") or MONTH_INDEX_TO_NAME.get(month_index, _format_label_text(month_hint))
    label = f"Week {derived_week_index} of {month_label}"

    return {
        "dates": dates,
        "week_index": derived_week_index,
        "month_label": month_label,
        "label": label,
        "weekdays_hint": list(weekdays_hint) if isinstance(weekdays_hint, (list, tuple, set)) else [],
    }


def preferred_weekday_label(
    preferred_weekdays: Sequence[int],
    sample_dates: Sequence[str],
) -> Optional[str]:
    """Generate a human-readable label for preferred weekdays.

    Extracted from step2_handler.py as part of D10 refactoring.

    Args:
        preferred_weekdays: List of weekday indices (0=Mon, 6=Sun)
        sample_dates: List of ISO date strings to check against

    Returns:
        Formatted label like "Fridays", "Fridays & Saturdays", or None
    """
    if not preferred_weekdays or not sample_dates:
        return None

    valid_indices = [idx for idx in preferred_weekdays if 0 <= idx <= 6]
    if not valid_indices:
        return None

    requested_set = set(valid_indices)
    sample_set: set[int] = set()

    for iso_value in sample_dates:
        try:
            parsed = datetime.fromisoformat(iso_value)
        except ValueError:
            continue
        weekday_idx = parsed.weekday()
        if weekday_idx in requested_set:
            sample_set.add(weekday_idx)

    if not sample_set:
        return None
    if not sample_set.issubset(requested_set):
        return None

    ordered_indices = [idx for idx in valid_indices if idx in sample_set]
    if not ordered_indices:
        ordered_indices = sorted(sample_set)

    labels = [f"{_WEEKDAY_LABELS[idx]}s" for idx in ordered_indices]
    if not labels:
        return None
    if len(labels) == 1:
        return labels[0]
    if len(labels) == 2:
        return f"{labels[0]} & {labels[1]}"
    return ", ".join(labels[:-1]) + f", & {labels[-1]}"


__all__ = [
    # Weekday alternatives (moved from step2_handler.py)
    "_collect_preferred_weekday_alternatives",
    # Candidate collection
    "collect_candidates_from_week_scope",
    "collect_candidates_from_fuzzy",
    "collect_candidates_from_constraints",
    "collect_candidates_from_suggestions",
    "collect_supplemental_candidates",
    # Prioritization
    "prioritize_by_weekday",
    # Payload building
    "build_table_and_actions",
    "build_draft_message",
    # Week scope resolution (D10)
    "resolve_week_scope",
    "preferred_weekday_label",
]
