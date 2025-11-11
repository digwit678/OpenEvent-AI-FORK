from __future__ import annotations

from typing import Any, Dict, Iterable, List


def _format_date_ddmmyyyy(date_iso: str | None) -> str:
    if not date_iso:
        return "TBD"
    token = date_iso.split("T")[0]
    if "-" in token:
        year, month, day = token.split("-")
    elif "." in token:
        day, month, year = token.split(".")
    else:
        return token
    return f"{day.zfill(2)}.{month.zfill(2)}.{year.zfill(4)}"


def _format_matched(matched: Iterable[str]) -> str:
    items = [item for item in matched if item]
    return ", ".join(items) if items else "None noted"


def _format_missing(missing: Iterable[str]) -> str:
    items = [item for item in missing if item]
    return ", ".join(items) if items else "Nothing missing"


def _extract_time(date_iso: str | None) -> str | None:
    if not date_iso or "T" not in date_iso:
        return None
    time_section = date_iso.split("T", 1)[1]
    clock = time_section.split("+")[0].split("Z")[0]
    hours, minutes, *_rest = clock.split(":") + ["00", "00"]
    return f"{hours}:{minutes}"


def render_rooms(
    event_id: str | None,
    date_iso: str | None,
    pax: int,
    rooms: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Render a deterministic Step-3 response for test flows."""

    display_date = _format_date_ddmmyyyy(date_iso)
    display_time = _extract_time(date_iso)
    confirmation_line = f"{display_date} is set."
    if display_time:
        confirmation_line = f"{display_date} {display_time} is set."
    body_lines = [
        confirmation_line,
        f"For {pax} people on {display_date}, here are the available rooms:",
    ]
    for room in rooms:
        name = room.get("name", "Room")
        capacity = room.get("capacity", "?")
        matched = _format_matched(room.get("matched", []))
        missing = _format_missing(room.get("missing", []))
        line = f"- {name} — capacity {capacity}. Matches: {matched}. Missing: {missing}."
        body_lines.append(line)
    body_lines.append("Let me know which room you prefer so I can send the offer.")
    return {
        "assistant_draft": {
            "headers": [f"Room options for {display_date}"],
            "body": "\n".join(body_lines),
        }
    }


__all__ = ["render_rooms"]
