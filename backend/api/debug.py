from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from backend.debug.trace import BUS
from backend.workflow.state import get_thread_state
from backend.debug import timeline
from fastapi.responses import PlainTextResponse


def debug_get_trace(thread_id: str) -> Dict[str, Any]:
    trace_payload = BUS.get(thread_id)
    state_snapshot = get_thread_state(thread_id) or {}
    if not state_snapshot:
        for event in reversed(trace_payload):
            if event.get("kind") == "STATE_SNAPSHOT":
                state_snapshot = dict(event.get("data") or {})
                break
    confirmed = _confirmed_map(state_snapshot)
    return {
        "thread_id": thread_id,
        "state": state_snapshot,
        "confirmed": confirmed,
        "trace": trace_payload,
        "timeline": timeline.snapshot(thread_id),
    }


def debug_get_timeline(thread_id: str) -> Dict[str, Any]:
    confirmed = _confirmed_map(get_thread_state(thread_id) or {})
    return {
        "thread_id": thread_id,
        "confirmed": confirmed,
        "trace": BUS.get(thread_id),
        "timeline": timeline.snapshot(thread_id),
    }


def resolve_timeline_path(thread_id: str) -> str:
    path = timeline.resolve_path(thread_id)
    return str(path) if path else ""


def render_arrow_log(thread_id: str) -> PlainTextResponse:
    events = BUS.get(thread_id)
    lines = _format_arrow_log(events)
    body = "\n".join(lines) if lines else "No trace events recorded."
    safe_id = thread_id.replace("/", "_").replace("\\", "_")
    filename = f"openevent_timeline_{safe_id}.txt"
    return PlainTextResponse(content=body, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def _format_arrow_log(events: Iterable[Dict[str, Any]]) -> List[str]:
    ordered = sorted(events, key=lambda ev: ev.get("ts") or 0)
    lines: List[str] = []
    for event in ordered:
        ts = event.get("ts")
        ts_label = _format_ts(ts)
        lane = event.get("lane") or ""
        kind = event.get("kind") or ""
        subject = event.get("subject") or event.get("step") or kind
        summary = event.get("summary") or event.get("detail") or ""
        status = event.get("status")
        loop = event.get("loop")
        detour_to = event.get("detour_to_step")

        prefix = f"[{ts_label}]"
        if lane == "db":
            line = f"{prefix} DB {summary or subject}"
        elif lane == "gate":
            verdict = status.upper() if status else kind.replace("GATE_", "")
            loop_marker = " ↺" if loop else ""
            line = f"{prefix} {event.get('step') or subject}{loop_marker} → Gate {verdict}: {summary}"
        elif lane == "entity":
            status_label = status.capitalize() if status else "Captured"
            line = f"{prefix} {event.get('step') or 'Entity'} → {status_label}: {summary or subject}"
        elif lane == "detour":
            arrow = f" → Step {detour_to}" if detour_to else ""
            line = f"{prefix} {subject}{arrow}: {summary}"
        elif lane == "draft":
            line = f"{prefix} Draft: {summary or subject}"
        elif lane == "qa":
            line = f"{prefix} QA: {summary or subject}"
        else:
            loop_marker = " ↺" if loop else ""
            line = f"{prefix} {subject}{loop_marker}: {summary or kind}"

        lines.append(line.strip())
    return lines


def _format_ts(ts: Any) -> str:
    if not ts:
        return "--:--:--"
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.strftime("%H:%M:%S")
    except Exception:
        return "--:--:--"


def _confirmed_map(snapshot: Dict[str, Any]) -> Dict[str, bool]:
    date_confirmed = bool(snapshot.get("date_confirmed"))
    room_locked = bool(snapshot.get("locked_room_id"))
    req_hash = snapshot.get("requirements_hash")
    room_hash = snapshot.get("room_eval_hash")
    hashes_match = bool(req_hash and room_hash and req_hash == room_hash)
    return {
        "date": date_confirmed,
        "room_locked": room_locked,
        "requirements_hash_matches": hashes_match,
    }


__all__ = [
    "debug_get_trace",
    "debug_get_timeline",
    "resolve_timeline_path",
    "render_arrow_log",
]
