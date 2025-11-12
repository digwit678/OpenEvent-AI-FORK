from __future__ import annotations

import re
from typing import Any, Dict

__all__ = ["validate_confirm_date_payload", "PayloadValidationError"]

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PayloadValidationError(ValueError):
    """Raised when an inbound action payload fails schema validation."""


def _normalise_string(value: Any, *, field: str) -> str:
    if isinstance(value, str):
        text = value.strip()
        if text:
            return text
    raise PayloadValidationError(f"Invalid or missing field '{field}'.")


def _validate_iso_date(value: str) -> str:
    if not _ISO_DATE_RE.fullmatch(value):
        raise PayloadValidationError("Date must be formatted as YYYY-MM-DD.")
    return value


def validate_confirm_date_payload(payload: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate the confirm_date action payload.

    Expected shape:
        {
            "action": "confirm_date",
            "event_id": "<event-id>",
            "date": "YYYY-MM-DD"
        }
    """

    if not isinstance(payload, dict):
        raise PayloadValidationError("Payload must be a JSON object.")

    action = _normalise_string(payload.get("action"), field="action")
    if action != "confirm_date":
        raise PayloadValidationError("Payload action must be 'confirm_date'.")

    event_id = _normalise_string(payload.get("event_id"), field="event_id")
    iso_date = _validate_iso_date(_normalise_string(payload.get("date"), field="date"))

    return {"event_id": event_id, "date": iso_date}
