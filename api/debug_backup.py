from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from debug.reporting import collect_trace_payload, filter_trace_events, generate_report
from debug.trace import BUS
from debug import timeline
from fastapi.responses import PlainTextResponse


def debug_get_trace(
    thread_id: str,
    *,
    granularity: str = "logic",
    kinds: Optional[List[str]] = None,
    as_of_ts: Optional[float] = None,
) -> Dict[str, Any]:
    return collect_trace_payload(thread_id, granularity=granularity, kinds=kinds, as_of_ts=as_of_ts)


def debug_get_timeline(
    thread_id: str,
    *,
    granularity: str = "logic",
    kinds: Optional[List[str]] = None,
    as_of_ts: Optional[float] = None,
) -> Dict[str, Any]:
    payload = collect_trace_payload(thread_id, granularity=granularity, kinds=kinds, as_of_ts=as_of_ts)
    return {
        "thread_id": thread_id,
        "confirmed": payload["confirmed"],
        "trace": payload["trace"],
        "timeline": payload["timeline"],
        "summary": payload["summary"],
        "time_travel": payload.get("time_travel"),
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
    events = filter_trace_events(BUS.get(thread_id), granularity, kinds)
    lines = _format_arrow_log(events)
    body = "\n".join(lines) if lines else "No trace events recorded."
    safe_id = thread_id.replace("/", "_").replace("\\", "_")
    filename = f"openevent_timeline_{safe_id}.txt"
    return PlainTextResponse(content=body, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


def debug_generate_report(
    thread_id: str,
    *,
    granularity: str = "logic",
    kinds: Optional[List[str]] = None,
    persist: bool = False,
) -> Tuple[str, Optional[str]]:
    body, saved_path = generate_report(thread_id, granularity=granularity, kinds=kinds, persist=persist)
    return body, str(saved_path) if saved_path else None


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
        entity_info = event.get("entity_context") or {}
        io_info = event.get("io") or event.get("db") or {}
        draft_info = (event.get("draft") or {}).get("footer") or {}

        prefix = f"[{ts_label}]"
        if lane == "db":
            op = io_info.get("op") or summary or subject
            mode = io_info.get("direction") or "DB"
            duration = (event.get("db") or {}).get("duration_ms")
            duration_hint = f" ({duration}ms)" if duration is not None else ""
            result = io_info.get("result")
            result_hint = f" → {result}" if result else ""
            line = f"{prefix} {mode} {op}{result_hint}{duration_hint}"
        elif lane == "gate":
            verdict = (gate_info.get("result") or status or kind).upper()
            met = gate_info.get("met")
            required = gate_info.get("required")
            missing = gate_info.get("missing") or []
            missing_hint = ""
            if missing:
                missing_hint = f" (missing: {', '.join(missing)})"
            loop_marker = " ↺" if loop else ""
            ratio = f" {met}/{required}" if met is not None and required is not None else ""
            line = f"{prefix} {event.get('step') or subject}{loop_marker} → Gate {verdict}{ratio}{missing_hint}"
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
            preview = event.get("prompt_preview")
            preview_hint = f" — {preview}" if preview else ""
            line = f"{prefix} Draft: {summary or subject}{footer_text}{preview_hint}"
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
    "debug_generate_report",
]