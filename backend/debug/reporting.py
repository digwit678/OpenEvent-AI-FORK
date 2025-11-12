from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union

from backend.debug import timeline
from backend.debug.trace import BUS, REQUIREMENTS_MATCH_HELP, get_trace_summary
from backend.workflow.state import get_thread_state

REPORT_ROOT = Path(__file__).resolve().parents[2] / "tmp-debug-reports"

MAX_FUNCTION_ARGS = 5
MAX_ARG_VALUE_LENGTH = 80
PROMPT_ARG_VALUE_LENGTH = 60
DETAIL_ARG_KEYS = ("args", "kwargs", "inputs", "parameters", "params", "payload")
PROMPT_ARG_KEYS = {"prompt_text", "message_text", "reply_text"}
DETAIL_IGNORE_KEYS = {"fn", "label", "kind", "path"}


def _ensure_report_dir() -> Path:
    REPORT_ROOT.mkdir(parents=True, exist_ok=True)
    return REPORT_ROOT


def _sanitise_thread_id(thread_id: str) -> str:
    safe = thread_id.replace("/", "_").replace("\\", "_").replace("..", "_")
    return safe or "unknown-thread"


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    if limit <= 1:
        return text[:1]
    return f"{text[: limit - 1]}…"


def _format_number(value: Union[int, float]) -> str:
    if isinstance(value, int):
        return f"{value:,}"
    formatted = f"{value:.3f}"
    if "." in formatted:
        formatted = formatted.rstrip("0").rstrip(".")
    return formatted


def _format_arg_value(key: str, value: Any) -> Optional[Tuple[str, str]]:
    if value is None:
        return ("null", "null")
    if isinstance(value, bool):
        text = "true" if value else "false"
        return (text, text)
    if isinstance(value, (int, float)):
        short = _format_number(value)
        full = str(value)
        return (short, full)
    if isinstance(value, str):
        normalized = " ".join(value.split())
        if not normalized:
            return ('""', '""')
        max_length = PROMPT_ARG_VALUE_LENGTH if key in PROMPT_ARG_KEYS else MAX_ARG_VALUE_LENGTH
        short = _truncate(normalized, max_length)
        return (short, normalized)
    try:
        serialized = json.dumps(value, ensure_ascii=False)
    except Exception:  # pragma: no cover - fallback for unserialisable values
        serialized = str(value)
    short = _truncate(serialized, MAX_ARG_VALUE_LENGTH)
    return (short, serialized)


def _is_plain_mapping(value: Any) -> bool:
    return isinstance(value, dict)


def _derive_function_args(event: Dict[str, Any], detail_object: Optional[Dict[str, Any]]) -> List[Dict[str, str]]:
    args: List[Dict[str, str]] = []
    seen: set[str] = set()

    def add_arg(key: str, value: Any) -> None:
        if len(args) >= MAX_FUNCTION_ARGS:
            return
        formatted = _format_arg_value(key, value)
        if not formatted:
            return
        short, full = formatted
        signature = f"{key}:{short}"
        if signature in seen:
            return
        seen.add(signature)
        args.append({"key": key, "value": short, "full_value": full})

    def process_mapping(source: Optional[Dict[str, Any]], ignore_keys: Optional[set[str]] = None) -> None:
        if not source:
            return
        for key, value in source.items():
            if len(args) >= MAX_FUNCTION_ARGS:
                break
            if ignore_keys and key in ignore_keys:
                continue
            add_arg(key, value)

    if detail_object:
        for candidate in DETAIL_ARG_KEYS:
            if len(args) >= MAX_FUNCTION_ARGS:
                break
            if candidate not in detail_object:
                continue
            value = detail_object[candidate]
            if _is_plain_mapping(value):
                process_mapping(value)  # type: ignore[arg-type]
            else:
                add_arg(candidate, value)
        skip_keys = set(DETAIL_IGNORE_KEYS).union(DETAIL_ARG_KEYS)
        process_mapping(detail_object, skip_keys)

    payload = event.get("payload")
    if _is_plain_mapping(payload):
        process_mapping(payload)  # type: ignore[arg-type]

    gate = event.get("gate")
    if _is_plain_mapping(gate):
        inputs = gate.get("inputs")
        if _is_plain_mapping(inputs):
            process_mapping(inputs)  # type: ignore[arg-type]

    return args


def _derive_function_info(event: Dict[str, Any]) -> Dict[str, Any]:
    detail_value = event.get("detail")
    detail_object = detail_value if _is_plain_mapping(detail_value) else None

    label: Optional[str] = None
    if detail_object:
        raw_label = detail_object.get("label")
        if isinstance(raw_label, str) and raw_label.strip():
            label = raw_label.strip()
        elif isinstance(detail_object.get("fn"), str):
            candidate = detail_object.get("fn")
            if candidate:
                label = str(candidate).strip()
    if label is None and isinstance(detail_value, str) and detail_value.strip():
        label = detail_value.strip()
    if label is None and isinstance(event.get("details"), str):
        detail_string = event["details"].strip()
        if detail_string:
            label = detail_string
    if label is None and isinstance(event.get("summary"), str):
        summary_text = event["summary"].strip()
        if summary_text:
            label = summary_text
    if label is None:
        label = event.get("event") or event.get("kind") or "event"

    path: Optional[str] = None
    if detail_object:
        path_candidate = detail_object.get("path")
        if isinstance(path_candidate, str) and path_candidate.strip():
            path = path_candidate.strip()
        else:
            fn_candidate = detail_object.get("fn")
            if isinstance(fn_candidate, str) and fn_candidate.strip():
                path = fn_candidate.strip()
    if path is None and isinstance(event.get("details"), str):
        candidate = event["details"].strip()
        if candidate:
            path = candidate
    if path is None and isinstance(label, str) and "." in label:
        path = label

    args = _derive_function_args(event, detail_object)
    return {"label": label, "path": path, "args": args}


def _format_timestamp(ts: Any) -> str:
    if not ts:
        return "--:--:--Z"
    try:
        dt = datetime.fromtimestamp(float(ts), tz=timezone.utc)
        return dt.isoformat()
    except Exception:  # pragma: no cover - defensive fallback
        return "--:--:--Z"


def _format_json_block(value: Any, *, indent: int = 2, prefix: str = "  ") -> List[str]:
    try:
        text = json.dumps(value, indent=indent, ensure_ascii=False, sort_keys=True)
    except Exception:  # pragma: no cover - fallback in case value is not serialisable
        text = str(value)
    return [f"{prefix}{line}" for line in text.splitlines()]


def filter_trace_events(
    events: Sequence[Dict[str, Any]],
    granularity: str,
    kinds: Optional[Sequence[str]],
) -> List[Dict[str, Any]]:
    granularity_normalized = (granularity or "logic").lower()
    if granularity_normalized == "logic":
        filtered = [ev for ev in events if (ev.get("granularity") or "verbose") == "logic"]
    elif granularity_normalized == "verbose":
        filtered = list(events)
    else:
        filtered = [ev for ev in events if (ev.get("granularity") or "verbose") == granularity_normalized]

    if kinds:
        allowed = {kind.lower() for kind in kinds}
        filtered = [ev for ev in filtered if (ev.get("lane") or "").lower() in allowed]
    return filtered


def _room_status(snapshot: Dict[str, Any]) -> Optional[str]:
    locked_room = snapshot.get("locked_room_id")
    if not locked_room:
        return "Unselected"
    status = snapshot.get("locked_room_status") or snapshot.get("selected_status") or snapshot.get("room_status")
    if isinstance(status, str):
        lowered = status.lower()
        if "available" in lowered:
            return "Available"
        if "option" in lowered:
            return "Option"
        if lowered in {"unavailable", "full", "closed"}:
            return "Unavailable"
        return status.strip() or "Available"
    return "Available"


def confirmed_map(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    chosen_date = snapshot.get("chosen_date") or snapshot.get("event_date") or snapshot.get("date")
    date_confirmed = bool(snapshot.get("date_confirmed"))
    room_status = _room_status(snapshot)
    req_hash = snapshot.get("requirements_hash") or snapshot.get("req_hash")
    room_hash = snapshot.get("room_eval_hash") or snapshot.get("eval_hash")
    requirements_match = snapshot.get("requirements_match")
    if requirements_match is None:
        requirements_match = bool(
            room_status != "Unselected"
            and req_hash
            and room_hash
            and str(req_hash) == str(room_hash)
        )
    requirements_match = bool(requirements_match)
    hash_status = None
    if req_hash and room_hash:
        hash_status = "Match" if requirements_match else "Mismatch"
    offer_status_display = snapshot.get("offer_status_display")
    offer_status = snapshot.get("offer_status")
    hil_open = bool(snapshot.get("hil_open"))
    if not offer_status_display:
        if isinstance(offer_status, str):
            lowered = offer_status.lower()
            if lowered == "accepted":
                offer_status_display = "Confirmed by HIL"
            elif hil_open:
                offer_status_display = "Waiting on HIL"
            elif lowered == "declined":
                offer_status_display = "Declined"
            elif lowered in {"draft", "drafting", "in creation"}:
                offer_status_display = "In creation"
            else:
                offer_status_display = offer_status.strip() or "—"
        else:
            offer_status_display = "—"
    if isinstance(offer_status, str):
        offer_status = offer_status.title()
    wait_state = snapshot.get("thread_state") or snapshot.get("threadState")
    return {
        "date": {"confirmed": date_confirmed, "value": chosen_date},
        "room_status": room_status,
        "requirements_match": requirements_match,
        "requirements_match_tooltip": REQUIREMENTS_MATCH_HELP,
        "hash_status": hash_status,
        "offer_status": offer_status,
        "offer_status_display": offer_status_display,
        "wait_state": wait_state,
    }


_MISSING = object()


def _state_snapshot_as_of(events: Sequence[Dict[str, Any]], as_of_ts: Optional[float]) -> Dict[str, Any]:
    if as_of_ts is None:
        return {}
    snapshot: Dict[str, Any] = {}
    for event in events:
        if event.get("kind") != "STATE_SNAPSHOT":
            continue
        ts = event.get("ts")
        if ts is not None and ts > as_of_ts:
            break
        snapshot = dict(event.get("data") or {})
    return snapshot


def _merge_state_with_unknowns(latest: Any, historical: Any = _MISSING) -> Any:
    if isinstance(latest, dict):
        historical_dict = historical if isinstance(historical, dict) else {}
        result: Dict[str, Any] = {}
        for key, value in latest.items():
            if isinstance(historical_dict, dict) and key in historical_dict:
                result[key] = _merge_state_with_unknowns(value, historical_dict[key])
            else:
                if isinstance(value, dict):
                    result[key] = _merge_state_with_unknowns(value, {})
                elif isinstance(value, list):
                    result[key] = [_merge_state_with_unknowns(item) for item in value]
                else:
                    result[key] = {"__unknown__": True, "__value__": value}
        if isinstance(historical_dict, dict):
            for key, hist_value in historical_dict.items():
                if key not in result:
                    result[key] = hist_value
        return result
    if isinstance(latest, list):
        historical_list = historical if isinstance(historical, list) else []
        merged: List[Any] = []
        for index, item in enumerate(latest):
            if isinstance(historical_list, list) and index < len(historical_list):
                merged.append(_merge_state_with_unknowns(item, historical_list[index]))
            else:
                if isinstance(item, dict):
                    merged.append(_merge_state_with_unknowns(item, {}))
                elif isinstance(item, list):
                    merged.append([_merge_state_with_unknowns(child) for child in item])
                else:
                    merged.append({"__unknown__": True, "__value__": item})
        return merged
    if historical is _MISSING:
        return {"__unknown__": True, "__value__": latest}
    return historical


def _summary_as_of(
    historical_state: Dict[str, Any],
    fallback_summary: Dict[str, Any],
    as_of_ts: float,
) -> Dict[str, Any]:
    summary = dict(fallback_summary or {})
    current_step = historical_state.get("current_step") or historical_state.get("step")
    try:
        summary["current_step_major"] = int(current_step)
    except (TypeError, ValueError):
        if "current_step_major" not in summary:
            summary["current_step_major"] = None
    summary["wait_state"] = historical_state.get("thread_state") or historical_state.get("threadState")
    summary["hil_open"] = bool(historical_state.get("hil_open"))
    hash_status = historical_state.get("hash_status")
    if hash_status:
        summary["hash_status"] = hash_status
    summary["time_travel"] = {"as_of_ts": as_of_ts}
    return summary


def collect_trace_payload(
    thread_id: str,
    *,
    granularity: str = "logic",
    kinds: Optional[Sequence[str]] = None,
    as_of_ts: Optional[float] = None,
) -> Dict[str, Any]:
    raw_events = BUS.get(thread_id)
    live_state = get_thread_state(thread_id) or {}
    if not live_state:
        for event in reversed(raw_events):
            if event.get("kind") == "STATE_SNAPSHOT":
                live_state = dict(event.get("data") or {})
                break

    historical_state = _state_snapshot_as_of(raw_events, as_of_ts) if as_of_ts is not None else None
    if as_of_ts is not None:
        state_snapshot = _merge_state_with_unknowns(live_state, historical_state or {})
        state_snapshot = dict(state_snapshot)
        state_snapshot["__time_travel"] = {"as_of_ts": as_of_ts}
        confirmed = confirmed_map(historical_state or {})
        fallback_summary = get_trace_summary(thread_id)
        summary = _summary_as_of(historical_state or {}, fallback_summary, as_of_ts)
        time_travel_meta = {"enabled": True, "as_of_ts": as_of_ts}
    else:
        state_snapshot = live_state
        confirmed = confirmed_map(state_snapshot)
        summary = get_trace_summary(thread_id)
        time_travel_meta = {"enabled": False}

    filtered_events = filter_trace_events(raw_events, granularity, kinds)
    return {
        "thread_id": thread_id,
        "state": state_snapshot,
        "confirmed": confirmed,
        "trace": filtered_events,
        "timeline": timeline.snapshot(thread_id),
        "summary": summary,
        "time_travel": time_travel_meta,
    }


def compose_debug_report(payload: Dict[str, Any]) -> str:
    thread_id = payload.get("thread_id", "unknown-thread")
    now = datetime.now(timezone.utc).isoformat()
    summary = payload.get("summary") or {}
    events = payload.get("trace") or []
    state_snapshot = payload.get("state") or {}
    confirmed = payload.get("confirmed") or {}
    timeline_entries = payload.get("timeline") or []

    lines: List[str] = []
    lines.append(f"Debug Report for {thread_id}")
    lines.append(f"Generated at {now}")
    lines.append(f"Events captured: {len(events)}")

    if summary:
        lines.append("")
        lines.append("Summary Signals:")
        for key, value in summary.items():
            lines.append(f"  - {key}: {value}")

    if state_snapshot:
        lines.append("")
        lines.append("State Snapshot:")
        lines.extend(_format_json_block(state_snapshot, indent=2, prefix="  "))

    if confirmed:
        lines.append("")
        lines.append("Confirmed Signals:")
        lines.extend(_format_json_block(confirmed, indent=2, prefix="  "))

    if timeline_entries:
        lines.append("")
        lines.append("Timeline Highlights:")
        for entry in timeline_entries:
            ts_label = _format_timestamp(entry.get("ts"))
            summary_text = entry.get("summary") or entry.get("event") or entry.get("kind") or ""
            lines.append(f"  - [{ts_label}] {summary_text}")

    lines.append("")
    lines.append("Detailed Events:")
    for index, event in enumerate(events, start=1):
        ts_label = _format_timestamp(event.get("ts"))
        step_label = event.get("step") or event.get("owner_step") or "—"
        entity = event.get("entity") or "—"
        actor = event.get("actor") or "—"
        kind = event.get("kind") or "—"
        event_label = event.get("event") or kind
        summary_text = event.get("summary") or ""
        function_info = _derive_function_info(event)
        lines.append(
            f"[{index}] {ts_label} | Step: {step_label} | Entity: {entity} | Actor: {actor} | Event: {event_label} ({kind})"
        )
        lines.append(f"  Path: {function_info.get('path') or '—'}")
        lines.append(f"  Function Label: {function_info.get('label')}")
        args = function_info.get("args") or []
        if args:
            lines.append("  Args:")
            for arg in args:
                lines.append(f"    • {arg['key']} = {arg['full_value']}")
        else:
            lines.append("  Args: —")

        captured = event.get("captured_additions") or []
        lines.append(f"  Captured Additions: {', '.join(captured) if captured else '—'}")
        confirmed_now = event.get("confirmed_now") or []
        lines.append(f"  Confirmed Now: {', '.join(confirmed_now) if confirmed_now else '—'}")

        gate = event.get("gate")
        if gate:
            ratio = f"{gate.get('met')}/{gate.get('required')}" if gate.get("met") is not None else ""
            result = gate.get("result") or gate.get("label") or ""
            missing = gate.get("missing") or []
            missing_text = f" missing={', '.join(missing)}" if missing else ""
            lines.append(f"  Gate: {result} {ratio}{missing_text}".strip())
        else:
            lines.append("  Gate: —")

        io_info = event.get("io") or event.get("db")
        if io_info:
            direction = io_info.get("direction") or io_info.get("mode")
            op = io_info.get("op")
            result = io_info.get("result")
            pieces = [piece for piece in (direction, op) if piece]
            line = "  IO: " + " ".join(pieces) if pieces else "  IO:"
            if result:
                line += f" → {result}"
            lines.append(line)
        else:
            lines.append("  IO: —")

        wait_state = event.get("wait_state")
        lines.append(f"  Wait State: {wait_state or '—'}")

        prompt_preview = event.get("prompt_preview")
        if prompt_preview:
            lines.append(f"  Prompt Preview: {prompt_preview}")

        if summary_text:
            lines.append(f"  Summary: {summary_text}")

        payload_block = event.get("payload") or {}
        if payload_block:
            lines.append("  Payload:")
            lines.extend(_format_json_block(payload_block, indent=4, prefix="    "))

        data_block = event.get("data")
        if data_block and data_block != payload_block:
            lines.append("  Data:")
            lines.extend(_format_json_block(data_block, indent=4, prefix="    "))

        detail_block = event.get("detail")
        if _is_plain_mapping(detail_block):
            lines.append("  Detail:")
            lines.extend(_format_json_block(detail_block, indent=4, prefix="    "))

        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def persist_debug_report(thread_id: str, body: str, *, granularity: str = "logic") -> Path:
    directory = _ensure_report_dir()
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H-%M-%S")
    filename = f"{timestamp}__{_sanitise_thread_id(thread_id)}__{granularity}.txt"
    path = directory / filename
    path.write_text(body, encoding="utf-8")
    return path


def generate_report(
    thread_id: str,
    *,
    granularity: str = "logic",
    kinds: Optional[Sequence[str]] = None,
    persist: bool = False,
) -> Tuple[str, Optional[Path]]:
    payload = collect_trace_payload(thread_id, granularity=granularity, kinds=kinds)
    body = compose_debug_report(payload)
    saved_path: Optional[Path] = None
    if persist:
        saved_path = persist_debug_report(thread_id, body, granularity=granularity)
    return body, saved_path


__all__ = [
    "filter_trace_events",
    "confirmed_map",
    "collect_trace_payload",
    "compose_debug_report",
    "persist_debug_report",
    "generate_report",
]