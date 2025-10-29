from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.workflows.common.billing import update_billing_details
from backend.workflows.common.types import WorkflowState


@dataclass(frozen=True)
class FieldSpec:
    alias: str
    path: Tuple[str, ...]
    step: int
    deferred: Optional[str] = None
    hold_until_owner: bool = False


_FIELD_SPECS: Dict[str, FieldSpec] = {
    # Step 2 — date & time window
    "date": FieldSpec(alias="date", path=("date",), step=2, deferred="date_confirmation"),
    "event_date": FieldSpec(alias="event_date", path=("event_date",), step=2, deferred="date_confirmation"),
    "start_time": FieldSpec(alias="start_time", path=("start_time",), step=2, deferred="date_confirmation"),
    "end_time": FieldSpec(alias="end_time", path=("end_time",), step=2, deferred="date_confirmation"),
    # Step 3 — room / requirements
    "room": FieldSpec(alias="room", path=("preferred_room",), step=3, deferred="room_selection"),
    "preferred_room": FieldSpec(alias="preferred_room", path=("preferred_room",), step=3, deferred="room_selection"),
    # Step 4/7 — billing & contacts
    "billing_address": FieldSpec(
        alias="billing_address",
        path=("billing", "address"),
        step=4,
        deferred="billing_update",
        hold_until_owner=True,
    ),
    "company": FieldSpec(
        alias="company",
        path=("billing", "company"),
        step=4,
        deferred="billing_update",
        hold_until_owner=True,
    ),
    "name": FieldSpec(alias="name", path=("contact", "name"), step=4, deferred="contact_update"),
    "email": FieldSpec(alias="email", path=("contact", "email"), step=4, deferred="contact_update"),
    "phone": FieldSpec(alias="phone", path=("contact", "phone"), step=4, deferred="contact_update"),
}


def capture_user_fields(state: WorkflowState, *, current_step: int, source: Optional[str] = None) -> None:
    """Capture out-of-order fields into the event entry for later promotion."""

    event_entry = state.event_entry
    user_info = state.user_info or {}
    if not event_entry or not user_info:
        return

    captured_root = event_entry.setdefault("captured", {})
    sources = event_entry.setdefault("captured_sources", [])
    deferred_intents = event_entry.setdefault("deferred_intents", [])

    telemetry_captured: List[str] = state.telemetry.setdefault("captured_fields", [])
    telemetry_deferred: List[str] = state.telemetry.setdefault("deferred_intents", list(deferred_intents))
    source_label = source or "user_message"

    for alias, spec in _FIELD_SPECS.items():
        if alias not in user_info:
            continue
        value = user_info[alias]
        if value in (None, "", [], {}):
            continue

        _set_nested(captured_root, spec.path, value)
        dotted = _path_to_str(spec.path)
        if dotted not in telemetry_captured:
            telemetry_captured.append(dotted)
        label = f"{source_label}:{dotted}"
        if label not in sources:
            sources.append(label)

        if spec.deferred and current_step < spec.step and spec.deferred not in deferred_intents:
            deferred_intents.append(spec.deferred)
        if spec.deferred and current_step < spec.step and spec.deferred not in telemetry_deferred:
            telemetry_deferred.append(spec.deferred)

        if spec.hold_until_owner and current_step < spec.step:
            user_info.pop(alias, None)

    # Keep telemetry deferred intents in sync with entry
    state.telemetry.deferred_intents = list(dict.fromkeys(deferred_intents))


def promote_fields(
    state: WorkflowState,
    event_entry: Dict[str, Any],
    promotions: Dict[Tuple[str, ...], Any],
    *,
    remove_deferred: Optional[Iterable[str]] = None,
) -> None:
    """Promote captured fields into the verified store and clean deferred intents."""

    if not promotions:
        return
    verified = event_entry.setdefault("verified", {})
    captured = event_entry.setdefault("captured", {})

    promoted_fields: List[str] = state.telemetry.setdefault("promoted_fields", [])

    for path, value in promotions.items():
        if value in (None, "", [], {}):
            continue
        _set_nested(verified, path, value)
        _delete_nested(captured, path)
        dotted = _path_to_str(path)
        if dotted not in promoted_fields:
            promoted_fields.append(dotted)

    if remove_deferred:
        deferred_intents = event_entry.setdefault("deferred_intents", [])
        for label in remove_deferred:
            if label in deferred_intents:
                deferred_intents.remove(label)
        state.telemetry.deferred_intents = list(dict.fromkeys(deferred_intents))


def get_captured_value(event_entry: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    """Return a captured field value given its path."""

    captured = event_entry.get("captured") or {}
    return _get_nested(captured, path)


def promote_billing_from_captured(state: WorkflowState, event_entry: Dict[str, Any]) -> None:
    """Promote captured billing fields into the event record when available."""

    promotions: Dict[Tuple[str, ...], Any] = {}
    address = get_captured_value(event_entry, ("billing", "address"))
    company = get_captured_value(event_entry, ("billing", "company"))

    if address not in (None, ""):
        event_entry.setdefault("event_data", {})["Billing Address"] = address
        promotions[("billing", "address")] = address

    if company not in (None, ""):
        event_entry.setdefault("event_data", {})["Company"] = company
        promotions[("billing", "company")] = company

    if not promotions:
        return

    update_billing_details(event_entry)
    promote_fields(state, event_entry, promotions, remove_deferred=["billing_update"])
    state.extras["persist"] = True


def _set_nested(container: Dict[str, Any], path: Tuple[str, ...], value: Any) -> None:
    cursor = container
    for key in path[:-1]:
        cursor = cursor.setdefault(key, {})
    cursor[path[-1]] = value


def _get_nested(container: Dict[str, Any], path: Tuple[str, ...]) -> Any:
    cursor = container
    for key in path:
        if not isinstance(cursor, dict) or key not in cursor:
            return None
        cursor = cursor[key]
    return cursor


def _delete_nested(container: Dict[str, Any], path: Tuple[str, ...]) -> None:
    stack: List[Tuple[Dict[str, Any], str]] = []
    cursor = container
    for key in path[:-1]:
        if key not in cursor or not isinstance(cursor[key], dict):
            return
        stack.append((cursor, key))
        cursor = cursor[key]
    cursor.pop(path[-1], None)
    # Clean up empty dicts
    while stack:
        parent, key = stack.pop()
        child = parent.get(key)
        if isinstance(child, dict) and not child:
            parent.pop(key, None)


def _path_to_str(path: Tuple[str, ...]) -> str:
    return ".".join(path)
