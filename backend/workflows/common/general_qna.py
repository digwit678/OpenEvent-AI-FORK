
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.workflows.common.capacity import fits_capacity, layout_capacity
from backend.workflows.common.catalog import list_catering, list_room_features
from backend.workflows.common.menu_options import build_menu_payload, format_menu_line
from backend.workflows.common.prompts import append_footer
from backend.workflows.common.types import GroupResult, WorkflowState
from backend.workflows.qna.router import route_general_qna

# TODO(openevent-team): Move extended room descriptions to dedicated metadata instead of the products mapping workaround.

ROOM_IDS = ["Room A", "Room B", "Room C"]
LAYOUT_KEYWORDS = {
    "u-shape": "U-shape",
    "u shape": "U-shape",
    "boardroom": "Boardroom",
    "board-room": "Boardroom",
}
FEATURE_KEYWORDS = {
    "projector": "Projector",
    "projectors": "Projector",
    "flipchart": "Flip chart",
    "flipcharts": "Flip chart",
    "flip chart": "Flip chart",
    "screen": "Screen",
    "hdmi": "HDMI",
    "sound system": "Sound system",
    "sound": "Sound system",
}
CATERING_KEYWORDS = {
    "lunch": "Light lunch",
    "coffee": "Coffee break service",
    "tea": "Coffee break service",
    "break": "Coffee break service",
}

STATUS_PRIORITY = {
    "available": 0,
    "option": 1,
    "hold": 2,
    "waitlist": 3,
    "unavailable": 4,
}

_DATE_PARSE_FORMATS = (
    "%Y-%m-%d",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%a %d %b %Y",
    "%A %d %B %Y",
)

DEFAULT_NEXT_STEP_LINE = "- Confirm your preferred date (and any other must-haves) so I can fast-track the next workflow step for you."
DEFAULT_ROOM_NEXT_STEP_LINE = "- Confirm the room you like (and any final requirements) so I can move ahead with the offer preparation."


def _normalise_iso_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidates = {text, text.replace("Z", ""), text.replace("Z", "+00:00")}
    for candidate in list(candidates):
        try:
            parsed = datetime.fromisoformat(candidate)
            return parsed.date().isoformat()
        except ValueError:
            continue
    for candidate in candidates:
        for fmt in _DATE_PARSE_FORMATS:
            try:
                parsed = datetime.strptime(candidate, fmt)
                return parsed.date().isoformat()
            except ValueError:
                continue
    return None


def _normalise_candidate_date(raw_date: str) -> Tuple[str, Optional[str]]:
    token = str(raw_date or "").strip()
    display_date = _format_display_date(token)
    iso_date = _normalise_iso_date(token) or _normalise_iso_date(display_date)
    return display_date, iso_date


def _range_results_lookup(range_results: Optional[Sequence[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
    mapping: Dict[str, List[Dict[str, Any]]] = {}
    if not range_results:
        return mapping
    for entry in range_results:
        if not isinstance(entry, dict):
            continue
        iso_date = (
            _normalise_iso_date(entry.get("iso_date"))
            or _normalise_iso_date(entry.get("date"))
            or _normalise_iso_date(entry.get("iso"))
            or _normalise_iso_date(entry.get("date_label"))
        )
        if not iso_date:
            continue
        record = {
            "room": entry.get("room") or entry.get("rooms") or entry.get("room_name"),
            "status": entry.get("status"),
            "summary": entry.get("summary"),
        }
        mapping.setdefault(iso_date, []).append(record)
    for rows in mapping.values():
        rows.sort(key=lambda rec: STATUS_PRIORITY.get(str(rec.get("status") or "").lower(), 9))
    return mapping


def _normalise_next_step_line(block_text: Optional[str], *, default_line: str = DEFAULT_NEXT_STEP_LINE) -> str:
    text = (block_text or "").strip()
    if not text:
        return default_line
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    bullet = next((line for line in lines if line.startswith("-")), None)
    if bullet:
        candidate = bullet.lstrip("- ").strip()
    else:
        candidate = re.sub(r"(?i)^next step:\s*", "", lines[0]).strip() if lines else ""
    if not candidate:
        return default_line
    candidate = candidate[0].upper() + candidate[1:] if candidate else candidate
    line = f"- {candidate}"
    if "fast-track" not in line.lower():
        stripped = line.rstrip(".")
        line = stripped + " — mention any other confirmed details (room/setup, catering) and I'll fast-track the next workflow step for you."
    return line



def _qna_message_payload(state: WorkflowState) -> Dict[str, str]:
    message = state.message
    subject = message.subject if message else ""
    body = message.body if message else ""
    return {
        "subject": subject or "",
        "body": body or "",
        "msg_id": message.msg_id if message else "",
        "thread_id": state.thread_id,
    }


def _extract_preference_tokens(text: str) -> Tuple[Optional[str], List[str], List[str]]:
    lowered = text.lower()
    layout = None
    for token, layout_name in LAYOUT_KEYWORDS.items():
        if token in lowered:
            layout = layout_name
            break

    features: List[str] = []
    for token, canonical in FEATURE_KEYWORDS.items():
        if token in lowered and canonical not in features:
            features.append(canonical)

    catering: List[str] = []
    for token, label in CATERING_KEYWORDS.items():
        if token in lowered and label not in catering:
            catering.append(label)

    return layout, features, catering


def _capture_preferences(state: WorkflowState, catering: Sequence[str], features: Sequence[str]) -> None:
    event_entry = state.event_entry or {}
    captured = event_entry.setdefault("captured", {})
    if catering:
        captured.setdefault("catering", list(catering))
    if features:
        captured.setdefault("products", list(features))
    state.event_entry = event_entry
    state.extras["captured_preferences"] = {"catering": list(catering), "features": list(features)}


def _room_feature_summary(room_id: str, features: Iterable[str]) -> str:
    matches: List[str] = []
    missing: List[str] = []
    available = set(map(str.strip, list_room_features(room_id)))
    for feature in features:
        if feature in available:
            matches.append(f"{feature} ✓")
        else:
            missing.append(f"{feature} ✗")
    summary_bits = matches[:2]
    if missing and not summary_bits:
        summary_bits.extend(missing[:1])
    elif missing:
        summary_bits.append(missing[0])
    return "; ".join(summary_bits)


def _room_recommendations(
    preferences: Dict[str, Any],
    participants: Optional[int],
) -> List[Dict[str, Any]]:
    layout = preferences.get("layout")
    features = preferences.get("features") or []

    recommendations: List[Dict[str, Any]] = []
    for room in ROOM_IDS:
        if participants and not fits_capacity(room, participants, layout):
            continue
        layout_note = ""
        if layout:
            capacity = layout_capacity(room, layout)
            if capacity:
                layout_note = f"{layout} up to {capacity}"
            else:
                layout_note = f"{layout} layout available"

        feature_summary = _room_feature_summary(room, features)
        score = feature_summary.count("✓")
        summary = ", ".join(filter(None, [layout_note, feature_summary])).strip(", ")
        recommendations.append(
            {
                "name": room,
                "summary": summary,
                "score": score,
            }
        )

    recommendations.sort(key=lambda entry: entry["score"], reverse=True)
    return recommendations[:3]


def _catering_recommendations(preferences: Dict[str, Any]) -> List[str]:
    catering_tokens = preferences.get("catering") or []
    if not catering_tokens:
        return []
    items = list_catering()
    selections: List[str] = []
    for label in catering_tokens:
        matched = next((item for item in items if label.lower() in str(item.get("name", "")).lower()), None)
        if matched:
            descriptor = matched.get("description") or matched.get("category") or "Package"
            price = matched.get("price_per_person") or matched.get("price")
            price_text = f" — CHF {price}" if price else ""
            selections.append(f"- {matched.get('name')}{price_text}: {descriptor}.")
        else:
            selections.append(f"- {label}.")
    return selections[:3]


def _preprocess_preferences(state: WorkflowState) -> Dict[str, Any]:
    payload = _qna_message_payload(state)
    text = f"{payload.get('subject', '')}\n{payload.get('body', '')}"
    layout, features, catering = _extract_preference_tokens(text)
    preferences = {
        "layout": layout,
        "features": features,
        "catering": catering,
    }
    _capture_preferences(state, catering, features)
    return preferences


def _split_body_footer(body: str) -> Tuple[str, Optional[str], Optional[str]]:
    """Split the body into core content, NEXT STEP block, and footer."""

    next_step_block: Optional[str] = None
    core_text = body

    next_step_match = re.search(r"(?:\n{2,}|^)(NEXT STEP:\n.*?)(?=\n{2,}|\Z)", body, flags=re.IGNORECASE | re.DOTALL)
    if next_step_match:
        next_step_block = next_step_match.group(1).strip()
        start, end = next_step_match.span()
        core_text = body[:start] + body[end:]
    else:
        inline_match = re.search(r"(?i)(next step:\s*.+)", core_text)
        if inline_match:
            line = inline_match.group(1).strip()
            instruction = re.sub(r"(?i)^next step:\s*", "", line).strip()
            if instruction:
                instruction = instruction[0].upper() + instruction[1:] if instruction else instruction
                next_step_block = f"NEXT STEP:\n- {instruction}"
            core_text = core_text.replace(inline_match.group(0), "")

    footer_text = None
    if "---" in core_text:
        core_part, _, footer_part = core_text.partition("---")
        core_text = core_part
        footer_text = footer_part.strip()

    return core_text.strip(), next_step_block, footer_text


def _build_room_and_catering_sections(
    state: WorkflowState,
    preferences: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], List[str], List[Dict[str, Any]], List[str]]:
    if preferences is None:
        preferences = _preprocess_preferences(state)
    participants = None
    try:
        participants = int((state.user_info or {}).get("participants") or (state.event_entry or {}).get("requirements", {}).get("number_of_participants") or 0)
    except (TypeError, ValueError):
        participants = None

    room_recs = _room_recommendations(preferences, participants)
    sections: List[str] = []
    headers: List[str] = []
    if (preferences.get("features") or preferences.get("layout")) and room_recs:
        lines = ["Rooms that already cover your requested setup:"]
        for rec in room_recs:
            bullet = f"- {rec['name']}"
            if rec["summary"]:
                bullet += f" — {rec['summary']}"
            lines.append(bullet)
        sections.append("Rooms & Setup\n" + "\n".join(lines))
        headers.append("Rooms & Setup")

    catering_lines = _catering_recommendations(preferences)
    if preferences.get("catering") and catering_lines:
        sections.append("Refreshments\n" + "\n".join(catering_lines))
        headers.append("Refreshments")

    return sections, headers, room_recs, catering_lines


def _menu_lines_from_payload(payload: Optional[Dict[str, Any]]) -> List[str]:
    if not payload:
        return []
    title = payload.get("title") or "Menu options we can offer:"
    lines = [title]
    for row in payload.get("rows", []):
        rendered = format_menu_line(row, month_hint=payload.get("month"))
        if rendered:
            lines.append(rendered)
    return lines


def _format_display_date(value: str) -> str:
    token = value.strip()
    if not token:
        return token
    if "." in token and token.count(".") == 2:
        return token
    cleaned = token.replace("Z", "")
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M"):
        try:
            parsed = datetime.strptime(cleaned, fmt)
            return parsed.strftime("%d.%m.%Y")
        except ValueError:
            continue
    try:
        parsed = datetime.fromisoformat(cleaned)
        return parsed.strftime("%d.%m.%Y")
    except ValueError:
        return token


def _extract_availability_lines(text: str) -> List[str]:
    lines: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("INFO:") or upper.startswith("NEXT STEP:"):
            continue
        if stripped.startswith("- "):
            continue
        if "available" in stripped.lower():
            lines.append(stripped)
    return lines


def _extract_info_lines(text: str) -> List[str]:
    capture = False
    info_lines: List[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        upper = stripped.upper()
        if upper.startswith("INFO:"):
            capture = True
            continue
        if upper.startswith("NEXT STEP:"):
            capture = False
            continue
        if capture and stripped.startswith("- "):
            info_lines.append(stripped)
    return info_lines


def _build_table_content(
    state: WorkflowState,
    candidate_dates: Sequence[str],
    range_results: Optional[Sequence[Dict[str, Any]]],
    room_recs: Sequence[Dict[str, Any]],
    catering_lines: Sequence[str],
) -> Tuple[List[str], List[Dict[str, Any]]]:
    if not candidate_dates:
        return [], []

    time_hint = (state.user_info or {}).get("vague_time_of_day") or (state.event_entry or {}).get("vague_time_of_day")
    time_note = str(time_hint).capitalize() if time_hint else ""
    catering_summary = "; ".join(item.strip("- ") for item in catering_lines[:2]) if catering_lines else ""

    range_map = _range_results_lookup(range_results)
    summary_map = {
        str(rec.get("name")).strip(): rec.get("summary")
        for rec in room_recs
        if rec.get("name")
    }

    table_lines: List[str] = []
    table_rows: List[Dict[str, Any]] = []

    def _unique_notes(bits: Sequence[str]) -> str:
        seen_local = set()
        ordered = []
        for item in bits:
            if item and item not in seen_local:
                ordered.append(item)
                seen_local.add(item)
        return "; ".join(ordered) if ordered else "—"

    use_room_first = bool(range_map)

    if use_room_first:
        room_rows: Dict[str, Dict[str, Any]] = {}
        handled_iso: set[str] = set()

        for raw_date in candidate_dates[:8]:
            display_date, iso_date = _normalise_candidate_date(raw_date)
            if iso_date:
                handled_iso.add(iso_date)
            entries = []
            if iso_date:
                entries = range_map.get(iso_date, [])
            if not entries and iso_date:
                entries = range_map.get(iso_date.split("T")[0], [])
            if not entries:
                continue
            for entry in entries:
                room_name = str(entry.get("room") or "").strip() or "Any matching room"
                bucket = room_rows.setdefault(
                    room_name,
                    {
                        "dates": [],
                        "iso_dates": [],
                        "statuses": set(),
                        "summaries": set(),
                        "min_status": 99,
                    },
                )
                bucket["dates"].append((iso_date or display_date, display_date))
                if iso_date:
                    bucket["iso_dates"].append(iso_date)
                status_text = str(entry.get("status") or "").strip()
                if status_text:
                    bucket["statuses"].add(status_text)
                    bucket["min_status"] = min(bucket["min_status"], STATUS_PRIORITY.get(status_text.lower(), 99))
                summary_text = str(entry.get("summary") or "").strip()
                if summary_text:
                    bucket["summaries"].add(summary_text)
                mapped_summary = summary_map.get(room_name)
                if mapped_summary:
                    bucket["summaries"].add(mapped_summary)

        # handle fallback rooms if candidate dates missing room info
        remaining_dates: List[Tuple[str, str]] = []
        for raw_date in candidate_dates[:8]:
            display_date, iso_date = _normalise_candidate_date(raw_date)
            if iso_date and iso_date in handled_iso:
                continue
            remaining_dates.append((iso_date or display_date, display_date))
        if remaining_dates:
            label = "Any matching room"
            bucket = room_rows.setdefault(
                label,
                {
                    "dates": [],
                    "iso_dates": [],
                    "statuses": set(),
                    "summaries": set(),
                    "min_status": 99,
                },
            )
            bucket["dates"].extend(remaining_dates[:5])
            bucket["iso_dates"].extend([pair[0] for pair in remaining_dates if pair[0]])

        if not room_rows and candidate_dates:
            # fallback to date-first table if no room data was captured
            use_room_first = False
        else:
            table_lines.extend(["| Room | Dates | Notes |", "| --- | --- | --- |"])
            for room_name, payload in sorted(
                room_rows.items(),
                key=lambda item: (
                    item[1]["min_status"],
                    min((pair[0] for pair in item[1]["dates"]), default=""),
                ),
            ):
                date_cells = []
                seen_dates = set()
                for sort_key, label in sorted(payload["dates"], key=lambda pair: pair[0]):
                    if label not in seen_dates:
                        date_cells.append(label)
                        seen_dates.add(label)
                dates_text = ", ".join(date_cells[:5]) if date_cells else "—"
                note_bits: List[str] = []
                if payload["summaries"]:
                    note_bits.append("; ".join(sorted(payload["summaries"])))
                if payload["statuses"]:
                    note_bits.append("Status: " + "/".join(sorted(payload["statuses"], key=str.lower)))
                if catering_summary:
                    note_bits.append(catering_summary)
                if time_note:
                    note_bits.append(time_note)
                notes_cell = _unique_notes(note_bits)

                table_lines.append(f"| {room_name} | {dates_text or '—'} | {notes_cell} |")
                row_payload: Dict[str, Any] = {
                    "room": room_name,
                    "dates": date_cells,
                    "notes": notes_cell,
                }
                if payload["iso_dates"]:
                    row_payload["iso_dates"] = payload["iso_dates"]
                    row_payload["iso_date"] = payload["iso_dates"][0]
                if payload["statuses"]:
                    row_payload["statuses"] = sorted(payload["statuses"], key=str.lower)
                table_rows.append(row_payload)

    if not use_room_first:
        table_lines = ["| Date | Room | Notes |", "| --- | --- | --- |"]
        table_rows = []
        rec_count = len(room_recs)
        rec_index = 0
        for raw_date in candidate_dates[:5]:
            display_date, iso_date = _normalise_candidate_date(raw_date)
            status_note = None
            room_label = None
            summary_note = None
            entries = []
            if iso_date and range_map:
                entries = range_map.get(iso_date, []) or range_map.get(iso_date.split("T")[0], [])
            if entries:
                entry = entries[0]
                room_label = str(entry.get("room") or "").strip() or "Let me know your preferred setup"
                status_note = entry.get("status")
                summary_note = entry.get("summary") or summary_map.get(room_label)
            elif rec_count:
                rec = room_recs[rec_index % rec_count]
                rec_index += 1
                room_label = str(rec.get("name") or "Let me know your preferred setup").strip()
                summary_note = rec.get("summary")
            else:
                room_label = "Let me know your preferred setup"

            rooms_cell = room_label
            if summary_note:
                rooms_cell = f"{room_label} — {summary_note}"

            notes_bits = []
            if status_note:
                notes_bits.append(str(status_note))
            if catering_summary:
                notes_bits.append(catering_summary)
            if time_note:
                notes_bits.append(time_note)

            notes_cell = _unique_notes(notes_bits)
            table_lines.append(f"| {display_date} | {rooms_cell} | {notes_cell} |")
            row_payload: Dict[str, Any] = {
                "date": display_date,
                "rooms": rooms_cell,
                "notes": notes_cell,
            }
            if iso_date:
                row_payload["iso_date"] = iso_date
            if status_note:
                row_payload["status"] = status_note
            table_rows.append(row_payload)

    return table_lines, table_rows


def enrich_general_qna_step2(state: WorkflowState, classification: Dict[str, Any]) -> None:
    if not state.draft_messages:
        return
    draft = state.draft_messages[-1]
    body_text = draft.get("body") or ""
    base_body, next_step_block, footer_tail = _split_body_footer(body_text)

    preferences = _preprocess_preferences(state)
    _sections, _headers, room_recs, catering_lines = _build_room_and_catering_sections(state, preferences)
    menu_payload = build_menu_payload(
        (state.message.body or "") if state.message else "",
        context_month=(state.event_entry or {}).get("vague_month"),
    )
    if menu_payload:
        state.turn_notes["general_qa"] = menu_payload

    candidate_dates = draft.get("candidate_dates") or []
    range_results = draft.get("range_results")
    table_lines, table_rows = _build_table_content(state, candidate_dates, range_results, room_recs, catering_lines)

    availability_lines = _extract_availability_lines(base_body)
    info_lines = _extract_info_lines(base_body)
    menu_lines = _menu_lines_from_payload(menu_payload)
    if not candidate_dates and not availability_lines:
        availability_lines = ["I need a specific date before I can confirm availability."]

    next_step_line = _normalise_next_step_line(next_step_block, default_line=DEFAULT_NEXT_STEP_LINE)

    body_segments: List[str] = ["General Q&A"]
    if menu_lines:
        body_segments.extend(menu_lines)
    if table_lines:
        body_segments.append("")
        body_segments.extend(table_lines)
    if availability_lines:
        body_segments.append("")
        body_segments.extend(availability_lines)
    if info_lines:
        body_segments.append("")
        body_segments.extend(info_lines)
    body_segments.append("")
    body_segments.append("NEXT STEP:")
    body_segments.append(next_step_line)

    body_markdown = "\n".join(segment for segment in body_segments if segment is not None).strip()

    footer_text = draft.get("footer")
    if not footer_text and footer_tail:
        footer_text = footer_tail
    else:
        footer_text = footer_text or "Step: 2 Date Confirmation · Next: Room Availability · State: Awaiting Client"

    draft["body_markdown"] = body_markdown
    draft["body"] = f"{draft['body_markdown']}\n\n---\n{footer_text}"
    draft["footer"] = footer_text
    draft["headers"] = ["General Q&A"]
    if table_rows:
        draft["table_blocks"] = [
            {
                "type": "dates",
                "label": "Dates & Rooms",
                "rows": table_rows,
            }
        ]


def render_general_qna_reply(state: WorkflowState, classification: Dict[str, Any]) -> Optional[GroupResult]:
    if not classification or not classification.get("is_general"):
        return None

    msg_payload = _qna_message_payload(state)
    event_entry_after = state.event_entry or {}
    classification_payload = dict(classification)
    classification_payload.setdefault("primary", "general_qna")
    secondary = list(classification_payload.get("secondary") or [])
    if "general" not in secondary and classification_payload.get("primary") == "general_qna":
        secondary.insert(0, "general")
    classification_payload["secondary"] = secondary

    qna_result = route_general_qna(
        msg_payload,
        event_entry_after,
        event_entry_after,
        state.db,
        classification_payload,
    )
    blocks = qna_result.get("post_step") or qna_result.get("pre_step") or []
    if not blocks:
        return None
    block = blocks[0]

    current_step = block.get("step") or qna_result.get("resume_step") or event_entry_after.get("current_step") or 2
    thread_state = event_entry_after.get("thread_state") or state.thread_state or "Awaiting Client"
    next_step_value = block.get("step") or current_step
    next_step = next_step_value if next_step_value != current_step else 3

    base_body_raw = block.get("body") or ""
    base_body, next_step_block, _ = _split_body_footer(base_body_raw)

    preferences = _preprocess_preferences(state)
    _sections, _headers, room_recs, catering_lines = _build_room_and_catering_sections(state, preferences)
    menu_payload = build_menu_payload(
        msg_payload.get("body"),
        context_month=event_entry_after.get("vague_month"),
    )
    if menu_payload:
        state.turn_notes["general_qa"] = menu_payload

    candidate_dates = block.get("candidate_dates") or []
    range_results = block.get("range_results")
    table_lines, table_rows = _build_table_content(state, candidate_dates, range_results, room_recs, catering_lines)
    availability_lines = _extract_availability_lines(base_body)
    info_lines = _extract_info_lines(base_body)
    menu_lines = _menu_lines_from_payload(menu_payload)
    if not candidate_dates and not availability_lines:
        availability_lines = ["I need a specific date before I can confirm availability."]

    default_line = DEFAULT_NEXT_STEP_LINE if current_step == 2 else DEFAULT_ROOM_NEXT_STEP_LINE
    next_step_line = _normalise_next_step_line(next_step_block, default_line=default_line)

    body_segments: List[str] = ["General Q&A"]
    if menu_lines:
        body_segments.extend(menu_lines)
    if table_lines:
        body_segments.append("")
        body_segments.extend(table_lines)
    if availability_lines:
        body_segments.append("")
        body_segments.extend(availability_lines)
    if info_lines:
        body_segments.append("")
        body_segments.extend(info_lines)
    body_segments.append("")
    body_segments.append("NEXT STEP:")
    body_segments.append(next_step_line)

    final_body = "\n".join(segment for segment in body_segments if segment is not None).strip()
    if not final_body:
        return None

    body_with_footer = append_footer(
        final_body,
        step=current_step,
        next_step=next_step,
        thread_state=thread_state,
    )

    table_blocks = []
    if table_rows:
        table_blocks.append(
            {
                "type": "dates",
                "label": "Dates & Rooms",
                "rows": table_rows,
            }
        )

    draft_message = {
        "body": body_with_footer,
        "body_markdown": final_body,
        "step": current_step,
        "topic": block.get("topic") or "general_information",
        "next_step": next_step,
        "thread_state": thread_state,
        "headers": ["General Q&A"],
        "requires_approval": False,
        "subloop": "general_q_a",
        "candidate_dates": block.get("candidate_dates"),
        "range_results": block.get("range_results"),
        "range_descriptor": block.get("range_descriptor"),
        "table_blocks": table_blocks,
    }

    state.record_subloop("general_q_a")
    state.extras["subloop"] = "general_q_a"
    state.add_draft_message(draft_message)
    state.set_thread_state(thread_state)

    payload = {
        "client_id": state.client_id,
        "event_id": event_entry_after.get("event_id"),
        "intent": state.intent.value if state.intent else None,
        "confidence": round(state.confidence or 0.0, 3),
        "draft_messages": state.draft_messages,
        "thread_state": state.thread_state,
        "context": state.context_snapshot,
        "persisted": False,
        "general_qna": True,
    }
    return GroupResult(action="general_rooms_qna", payload=payload, halt=True)


def maybe_handle_general_qna_for_step(state: WorkflowState) -> Optional[GroupResult]:
    event_entry = state.event_entry or {}
    current_step = event_entry.get("current_step")
    if current_step == 2:
        return None

    classification = state.extras.get("_general_qna_classification")
    if not classification or not classification.get("is_general"):
        return None

    return render_general_qna_reply(state, classification)


__all__ = ["maybe_handle_general_qna_for_step", "render_general_qna_reply", "enrich_general_qna_step2"]
