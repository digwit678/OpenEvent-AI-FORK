from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import uuid
from typing import Any, Dict

from workflow_email import process_msg as wf_process_msg


def advance_after_review(message_payload: Dict[str, Any]) -> Dict[str, Any]:
    """Replay the original client message after manual review approval."""

    payload = deepcopy(message_payload or {})
    original_id = str(payload.get("msg_id") or "reviewed-message")
    payload["msg_id"] = f"{original_id}-approved-{uuid.uuid4().hex[:8]}"
    payload.setdefault("from_email", payload.get("from_email") or "unknown@example.com")
    payload.setdefault("from_name", payload.get("from_name") or "Client")
    payload.setdefault("subject", payload.get("subject") or "Client message")
    payload.setdefault("ts", payload.get("ts") or datetime.utcnow().isoformat() + "Z")
    return wf_process_msg(payload)
