from __future__ import annotations

from typing import Any, Dict, List

_DEFAULT_GATE = {"step2": False, "step3": False, "step4": False, "step7": False}
_ACCEPTED_STATUSES = {"accepted", "accepted_final"}


def ensure_gatekeeper_state(event_entry: Dict[str, Any]) -> Dict[str, bool]:
    """Ensure the event entry exposes a mutable gatekeeper status structure."""

    gatekeeper = event_entry.setdefault("gatekeeper_passed", dict(_DEFAULT_GATE))
    for key, value in _DEFAULT_GATE.items():
        if key not in gatekeeper:
            gatekeeper[key] = value
    return gatekeeper


def refresh_gatekeeper(event_entry: Dict[str, Any]) -> Dict[str, bool]:
    """Recompute the gatekeeper status flags for the canonical steps."""

    gatekeeper = ensure_gatekeeper_state(event_entry)
    gatekeeper["step2"] = _step2_complete(event_entry)
    gatekeeper["step3"] = _step3_complete(event_entry)
    gatekeeper["step4"] = _step4_complete(event_entry)
    explain = explain_step7_gate(event_entry)
    gatekeeper["step7"] = explain["ready"]
    event_entry["gatekeeper_passed"] = gatekeeper
    event_entry["gatekeeper_explain"] = explain
    return gatekeeper


def _step2_complete(event_entry: Dict[str, Any]) -> bool:
    window = event_entry.get("requested_window") or {}
    return bool(window.get("start") and window.get("end") and window.get("tz"))


def _step3_complete(event_entry: Dict[str, Any]) -> bool:
    return bool(event_entry.get("locked_room_id"))


def _step4_complete(event_entry: Dict[str, Any]) -> bool:
    if not event_entry.get("offer_hash"):
        return False
    line_items = (event_entry.get("products_state") or {}).get("line_items")
    if line_items is None:
        return True
    return all(_valid_line_item(entry) for entry in line_items)


def _valid_line_item(entry: Dict[str, Any]) -> bool:
    if not isinstance(entry, dict):
        return False
    name = str(entry.get("name") or entry.get("description") or "").strip()
    if not name:
        return False
    quantity = entry.get("quantity")
    if quantity is None:
        return False
    try:
        return int(quantity) > 0
    except (TypeError, ValueError):
        return False


def explain_step7_gate(event_entry: Dict[str, Any]) -> Dict[str, Any]:
    """Return minimal confirmation gating details for step 7."""

    missing: List[str] = []

    if not bool(event_entry.get("date_confirmed")):
        missing.append("date_confirmed")

    locked_room = event_entry.get("locked_room_id")
    if isinstance(locked_room, str):
        locked_ready = bool(locked_room.strip())
    else:
        locked_ready = bool(locked_room)
    if not locked_ready:
        missing.append("locked_room_id")

    offer_status = str(event_entry.get("offer_status") or "").strip().lower()
    offer_gate_ready = bool(event_entry.get("offer_gate_ready"))
    if offer_status not in _ACCEPTED_STATUSES and not offer_gate_ready:
        missing.append("offer_status")

    event_data = event_entry.get("event_data") or {}
    # Check canonical event_data fields first, then fall back to captured.billing
    captured_billing = (event_entry.get("captured") or {}).get("billing") or {}
    company = (
        str(event_data.get("Company") or "").strip()
        or str(captured_billing.get("company") or "").strip()
    )
    billing_address = (
        str(event_data.get("Billing Address") or "").strip()
        or str(captured_billing.get("address") or "").strip()
    )

    if not company:
        missing.append("billing.company")
    if not billing_address:
        missing.append("billing.address")

    ready = not missing
    reason = "ready" if ready else missing[0]

    return {
        "ready": ready,
        "missing_now": missing,
        "reason": reason,
    }
