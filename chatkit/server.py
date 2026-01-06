from __future__ import annotations

from datetime import datetime
import json
from typing import Any, AsyncGenerator, Dict, Optional

from fastapi.responses import StreamingResponse

from backend.agents import run_streamed

CLIENT_TOOL_DEFAULTS = {
    "confirm_offer": "Please confirm the offer.",
    "change_offer": "Let's adjust the offer.",
    "discard_offer": "Discard the current offer draft.",
    "see_catering": "What catering options are available?",
    "see_products": "Which products or equipment can be added?",
}


def build_client_tool_message(payload: Dict[str, Any]) -> str:
    """
    Convert a client tool payload into a deterministic textual prompt.
    """

    tool = payload.get("client_tool")
    args = payload.get("args") or {}
    base = CLIENT_TOOL_DEFAULTS.get(str(tool), "")

    if tool == "change_offer":
        note = str(args.get("note", "")).strip()
        if note:
            return f"Let's adjust the offer: {note}"
    elif tool in {"see_catering", "see_products"}:
        room_id = str(args.get("room_id") or "").strip()
        if room_id:
            if tool == "see_catering":
                return f"What catering options are available for {room_id}?"
            return f"Which products or equipment can be added to {room_id}?"
    elif tool == "confirm_offer":
        note = str(args.get("note", "")).strip()
        if note:
            return f"Please confirm the offer and note: {note}"

    if base:
        return base
    return json.dumps(payload)


async def respond(request) -> StreamingResponse:
    """
    Stream ChatKit responses using the step-aware agent runner.

    The request object is expected to mirror ChatKitMessage from the API layer.
    """

    thread_id = request.thread_id
    tool_payload: Optional[Dict[str, Any]] = None
    body_text = request.text or ""
    try:
        maybe_json = json.loads(request.text)
        if isinstance(maybe_json, dict) and "client_tool" in maybe_json:
            tool_payload = maybe_json
            body_text = build_client_tool_message(tool_payload)
    except (TypeError, ValueError):
        # Not JSON; leave body_text as-is.
        pass

    message_payload: Dict[str, Any] = {
        "msg_id": f"chatkit-{datetime.utcnow().timestamp()}",
        "from_name": request.from_name or "Client (ChatKit)",
        "from_email": request.from_email or "unknown@example.com",
        "subject": request.subject or "Client message",
        "ts": datetime.utcnow().isoformat() + "Z",
        "body": body_text,
        "attachments": request.attachments or [],
        "thread_id": thread_id,
    }
    state = {
        "thread_id": thread_id,
        "current_step": request.current_step,
        "status": request.status,
        "client_tool": tool_payload,
    }

    async def event_stream() -> AsyncGenerator[str, None]:
        async for chunk in run_streamed(thread_id, message_payload, state):
            yield chunk

    return StreamingResponse(event_stream(), media_type="text/event-stream")
