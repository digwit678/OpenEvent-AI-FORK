from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional

from backend.debug.trace import BUS
from backend.workflow.state import get_thread_state
from backend.debug import timeline
from fastapi.responses import PlainTextResponse


def debug_get_trace(
    thread_id: str,
    *,
    granularity: str = "logic",
    kinds: Optional[List[str]] = None,
) -> Dict[str, Any]:
    raw_events = BUS.get(thread_id)
    state_snapshot = get_thread_state(thread_id) or {}
    if not state_snapshot:
        for event in reversed(raw_events):
            if event.get("kind") == "STATE_SNAPSHOT":
                state_snapshot = dict(event.get("data") or {})
                break
    confirmed = _confirmed_map(state_snapshot)
    filtered_events = _apply_filters(raw_events, granularity, kinds)
    return {
        "thread_id": thread_id,
        "state": state_snapshot,
        "confirmed": confirmed,
        "trace": filtered_events,
        "timeline": timeline.snapshot(thread_id),
    }


def debug_get_timeline(
    thread_id: str,
    *,
    granularity: str = "logic",
    kinds: Optional[List[str]] = None,
) -> Dict[str, Any]:
    confirmed = _confirmed_map(get_thread_state(thread_id) or {})
    return {
        "thread_id": thread_id,
        "confirmed": confirmed,
        "trace": _apply_filters(BUS.get(thread_id), granularity, kinds),
        "timeline": timeline.snapshot(thread_id),
    }


def resolve_timeline_path(thread_id: str) -> str:
    path = timeline.resolve_path(thread_id)
    return str(path) if path else ""


def render_arrow_log(
    thread_id: str,
    *,
    granularity: str = "logic",
    kinds: Optional[List[str]] = None,
) -> PlainTextResponse:
    events = _apply_filters(BUS.get(thread_id), granularity, kinds)
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
        gate_info = event.get("gate") or {}
        entity_info = event.get("entity") or {}
        db_info = event.get("db") or {}
        draft_info = (event.get("draft") or {}).get("footer") or {}

        prefix = f"[{ts_label}]"
        if lane == "db":
            op = db_info.get("op") or summary or subject
            mode = db_info.get("mode") or "DB"
            duration = db_info.get("duration_ms")
            duration_hint = f" ({duration}ms)" if duration is not None else ""
            line = f"{prefix} {mode} {op}{duration_hint}"
        elif lane == "gate":
            verdict = (gate_info.get("result") or status or kind).upper()
            inputs = gate_info.get("inputs") or {}
            input_preview = ""
            if inputs:
                shortened = ", ".join(f"{key}={_stringify(value)}" for key, value in list(inputs.items())[:3])
                input_preview = f" (inputs: {shortened})"
            loop_marker = " ↺" if loop else ""
            line = f"{prefix} {event.get('step') or subject}{loop_marker} → Gate {verdict}{input_preview}"
        elif lane == "entity":
            lifecycle = entity_info.get("lifecycle") or status or "captured"
            key = entity_info.get("key") or subject
            value = entity_info.get("value")
            previous = entity_info.get("previous_value")
            delta = f" (prev: {previous})" if previous is not None else ""
            line = f"{prefix} {event.get('step') or 'Entity'} → {lifecycle.capitalize()}: {key}={_stringify(value)}{delta}"
        elif lane == "detour":
            arrow = f" → Step {detour_to}" if detour_to else ""
            reason = (event.get("detour") or {}).get("reason") or summary or ""
            line = f"{prefix} {subject}{arrow}: {reason}"
        elif lane == "draft":
            next_step = draft_info.get("next")
            wait_state = draft_info.get("state")
            footer_bits = []
            if next_step:
                footer_bits.append(f"next: {next_step}")
            if wait_state:
                footer_bits.append(f"state: {wait_state}")
            footer_text = f" ({', '.join(footer_bits)})" if footer_bits else ""
            line = f"{prefix} Draft: {summary or subject}{footer_text}"
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


def _apply_filters(
    events: List[Dict[str, Any]],
    granularity: str,
    kinds: Optional[List[str]],
) -> List[Dict[str, Any]]:
    granularity_normalized = (granularity or "logic").lower()
    filtered = events
    if granularity_normalized == "logic":
        filtered = [ev for ev in events if (ev.get("granularity") or "verbose") == "logic"]
    elif granularity_normalized == "verbose":
        filtered = events
    else:
        filtered = [ev for ev in events if (ev.get("granularity") or "verbose") == granularity_normalized]

    if kinds:
        allowed = {kind.lower() for kind in kinds}
        filtered = [ev for ev in filtered if (ev.get("lane") or "").lower() in allowed]
    return filtered


def _stringify(value: Any) -> str:
    text = str(value)
    if len(text) > 60:
        return f"{text[:57]}…"
    return text


__all__ = [
    "debug_get_trace",
    "debug_get_timeline",
    "resolve_timeline_path",
    "render_arrow_log",
]
