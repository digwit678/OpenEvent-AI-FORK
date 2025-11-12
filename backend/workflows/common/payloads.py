from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict

__all__ = ["PayloadValidationError", "validate_confirm_date_payload"]

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PayloadValidationError(ValueError):
    """Raised when workflow payloads fail schema validation."""


def validate_confirm_date_payload(payload: Dict[str, Any]) -> None:
    """
    Ensure confirm-date payloads contain the expected keys and formats.

    Expected structure::
        {
            "action": "confirm_date",
            "event_id": "<uuid>",
            "date": "YYYY-MM-DD",
        }
    """

    if not isinstance(payload, dict):
        raise PayloadValidationError("Payload must be a dictionary.")

    action = payload.get("action")
    if action != "confirm_date":
        raise PayloadValidationError(f"Invalid action '{action}'. Expected 'confirm_date'.")

    event_id = payload.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        raise PayloadValidationError("event_id must be a non-empty string.")

    date_value = payload.get("date")
    if not isinstance(date_value, str) or not ISO_DATE_RE.fullmatch(date_value):
        raise PayloadValidationError("date must be a string formatted as YYYY-MM-DD.")

    try:
        datetime.strptime(date_value, "%Y-%m-%d")
    except ValueError as exc:
        raise PayloadValidationError(f"date is not a valid calendar day: {exc}") from exc
