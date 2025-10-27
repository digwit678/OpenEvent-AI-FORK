from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from backend.domain.vocabulary import IntentLabel

from backend.workflows.common.timeutils import parse_ddmmyyyy


def is_event_request(intent: IntentLabel) -> bool:
    """[Condition] Check if the classified intent maps to an event request."""

    return intent in {
        IntentLabel.EVENT_REQUEST,
        IntentLabel.CONFIRM_DATE,
        IntentLabel.CONFIRM_DATE_PARTIAL,
        IntentLabel.EDIT_DATE,
        IntentLabel.EDIT_ROOM,
        IntentLabel.EDIT_REQUIREMENTS,
    }


def has_event_date(user_info: Dict[str, Any]) -> bool:
    """[Condition] Determine whether the extracted info includes a valid ISO event date."""

    date_val = user_info.get("date")
    if not date_val:
        return False
    try:
        parse = date_val.replace("Z", "+00:00")
        datetime.fromisoformat(parse)
    except ValueError:
        return False
    return True


def is_valid_ddmmyyyy(date_str: Optional[str]) -> bool:
    """[Condition] Validate DD.MM.YYYY date strings extracted from replies."""

    if not date_str:
        return False
    return parse_ddmmyyyy(date_str) is not None
