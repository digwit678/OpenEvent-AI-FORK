from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.workflows.common.capacity import alternative_rooms, fits_capacity, layout_capacity
from backend.workflows.common.catalog import (
    list_catering,
    list_free_dates,
    list_products,
    list_room_features,
    list_rooms_by_feature,
)
from backend.workflows.qna.templates import build_info_block, build_next_step_line

_ROOM_NAMES = ("Room A", "Room B", "Room C", "Punkt.Null")
_FEATURE_KEYWORDS = {
    "hdmi": "HDMI",
    "projector": "Projector",
    "screen": "Screen",
    "video": "Video conferencing",
    "record": "Recording capability",
    "whiteboard": "Whiteboard",
    "daylight": "Natural daylight",
    "sound": "sound system",
}
_LAYOUT_KEYWORDS = {
    "u-shape": "U-shape",
    "ushape": "U-shape",
    "u shape": "U-shape",
    "theater": "Theater",
    "theatre": "Theater",
    "classroom": "Classroom",
    "boardroom": "Boardroom",
    "banquet": "Banquet",
    "standing": "Standing reception",
}
_ATTENDEE_PATTERN = re.compile(r"(\d{1,3})\s*(?:guests|people|ppl|attendees)", re.IGNORECASE)
_ROOM_PATTERN = re.compile(r"\broom\s*([abc])\b", re.IGNORECASE)
_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}


def _with_preface(lines: List[str], preface: Optional[str]) -> List[str]:
    """Return a new list with an optional lead sentence ahead of the info lines."""

    cleaned = (preface or "").strip()
    if not cleaned:
        return lines
    if lines and lines[0].strip() == cleaned:
        return lines
    return [cleaned, *lines]


def _message_text(msg: Dict[str, Any]) -> str:
    subject = str(msg.get("subject") or "").strip()
    body = str(msg.get("body") or "").strip()
    if subject and body:
        return f"{subject}\n{body}"
    return subject or body


def _current_step(event_entry: Optional[Dict[str, Any]]) -> int:
    if event_entry and isinstance(event_entry.get("current_step"), int):
        return int(event_entry["current_step"])
    return 2


def _extract_attendees(text: str, fallback: Optional[Any]) -> Optional[int]:
    match = _ATTENDEE_PATTERN.search(text)
    if match:
        try:
            return int(match.group(1))
        except ValueError:
            pass
    if fallback is None:
        return None
    try:
        return int(fallback)
    except (TypeError, ValueError):
        return None


def _extract_layout(text: str, fallback: Optional[str]) -> Optional[str]:
    lowered = text.lower()
    for token, layout in _LAYOUT_KEYWORDS.items():
        if token in lowered:
            return layout
    return fallback


def _extract_feature_tokens(text: str) -> List[str]:
    lowered = text.lower()
    features: List[str] = []
    for token, canonical in _FEATURE_KEYWORDS.items():
        if token in lowered and canonical not in features:
            features.append(canonical)
    return features


def _extract_requested_room(text: str) -> Optional[str]:
    lowered = text.lower()
    for name in _ROOM_NAMES:
        if name.lower() in lowered:
            return name
    alias = _ROOM_PATTERN.search(lowered)
    if alias:
        letter = alias.group(1).upper()
        return f"Room {letter}"
    if "punkt" in lowered:
        return "Punkt.Null"
    return None


def _extract_anchor(text: str) -> Tuple[Optional[int], Optional[int]]:
    lowered = text.lower()
    for name, month in _MONTHS.items():
        if name in lowered:
            day_match = re.search(rf"(\d{{1,2}})\s+(?:of\s+)?{name}", lowered)
            if day_match:
                try:
                    return month, int(day_match.group(1))
                except ValueError:
                    return month, None
            return month, None
    return None, None


def _event_requirements(event_entry: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not event_entry:
        return {}
    requirements = event_entry.get("requirements")
    if isinstance(requirements, dict):
        return requirements
    return {}


def _event_attendees(event_entry: Optional[Dict[str, Any]]) -> Optional[int]:
    requirements = _event_requirements(event_entry)
    value = requirements.get("number_of_participants")
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _event_layout(event_entry: Optional[Dict[str, Any]]) -> Optional[str]:
    requirements = _event_requirements(event_entry)
    layout = requirements.get("seating_layout")
    if isinstance(layout, str) and layout.strip():
        return layout
    return None


def _event_room(event_entry: Optional[Dict[str, Any]]) -> Optional[str]:
    if not event_entry:
        return None
    locked = event_entry.get("locked_room_id")
    if locked:
        return locked
    requirements = _event_requirements(event_entry)
    preferred = requirements.get("preferred_room")
    if preferred:
        return preferred
    return None


def _event_date_iso(event_entry: Optional[Dict[str, Any]]) -> Optional[str]:
    if not event_entry:
        return None
    window = event_entry.get("requested_window") or {}
    iso_value = window.get("date_iso")
    if iso_value:
        return iso_value
    chosen = event_entry.get("chosen_date")
    if not chosen:
        return None
    try:
        parsed = datetime.strptime(chosen, "%d.%m.%Y")
        return parsed.strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return None


def _missing_fields(step: int, event_entry: Optional[Dict[str, Any]]) -> List[str]:
    missing: List[str] = []
    if not event_entry:
        if step == 2:
            missing.extend(["date", "time"])
        return missing

    if step == 2:
        window = event_entry.get("requested_window") or {}
        if not window.get("date_iso"):
            missing.append("date")
        if not (window.get("start_time") and window.get("end_time")):
            missing.append("time")
    elif step == 3:
        if not event_entry.get("locked_room_id"):
            missing.append("room")
        requirements = _event_requirements(event_entry)
        if not requirements.get("number_of_participants"):
            missing.append("attendees")
        if not requirements.get("seating_layout"):
            missing.append("layout")
    elif step == 4:
        products = event_entry.get("products") or []
        selected = event_entry.get("selected_products") or []
        if not products and not selected:
            missing.append("products")
        event_data = event_entry.get("event_data") or {}
        catering_pref = str(event_data.get("Catering Preference") or "").strip()
        if not catering_pref or catering_pref.lower() == "not specified":
            missing.append("catering")
    return missing


def _rooms_by_feature_response(
    text: str,
    event_entry: Optional[Dict[str, Any]],
    attendees: Optional[int],
    layout: Optional[str],
) -> List[str]:
    requested_room = _extract_requested_room(text)
    feature_tokens = _extract_feature_tokens(text)
    features_to_check = feature_tokens or ["Natural daylight"]
    info_lines: List[str] = []

    if requested_room and attendees is not None and not fits_capacity(requested_room, attendees, layout):
        descriptor = f"{attendees} guests"
        if layout:
            descriptor = f"{attendees} guests in {layout}"
        info_lines.append(f"{requested_room} cannot comfortably host {descriptor}.")
        alternatives = alternative_rooms(_event_date_iso(event_entry), attendees, layout)
        if alternatives:
            for alt in alternatives[:3]:
                cap_text = ""
                if alt.get("layout_max"):
                    cap_text = f" ({layout or 'requested layout'} up to {alt['layout_max']})"
                elif alt.get("max"):
                    cap_text = f" (up to {alt['max']} guests)"
                info_lines.append(f"Consider {alt['name']}{cap_text}.")
        if not info_lines:
            info_lines.append("Let me know if you'd like me to suggest another room.")
        return _with_preface(info_lines, f"I checked {requested_room} for you:")

    for feature in features_to_check:
        rooms = list_rooms_by_feature(feature, min_capacity=attendees, layout=layout)
        if rooms:
            for room in rooms[:3]:
                layout_cap = room.get("layout_capacity")
                capacity_bits: List[str] = []
                if layout_cap:
                    capacity_bits.append(f"{layout or 'layout'} up to {layout_cap}")
                elif room.get("max_capacity"):
                    capacity_bits.append(f"up to {room['max_capacity']} guests")
                feature_bits = room.get("features") or []
                highlight = ", ".join(feature_bits[:2]) if feature_bits else feature
                cap_text = f" ({'; '.join(capacity_bits)})" if capacity_bits else ""
                suffix = f"; {highlight}" if highlight else ""
                info_lines.append(f"{room['name']}{cap_text}{suffix}.")
            break

    if requested_room and not info_lines:
        feature_list = list_room_features(requested_room)
        if feature_list:
            primary = ", ".join(feature_list[:3])
            info_lines.append(f"{requested_room} includes {primary}.")

    if not info_lines:
        info_lines.append("All rooms include Wi-Fi, daylight, and flexible seating.")
    if feature_tokens:
        joined = ", ".join(feature_tokens)
        preface = f"Since you asked about {joined}, here are rooms that already cover that:"
    elif requested_room:
        preface = f"Here's what we can offer in {requested_room}:"
    else:
        preface = "Here are a few rooms that should fit what you're looking for:"
    return _with_preface(info_lines, preface)


def _room_features_response(text: str, event_entry: Optional[Dict[str, Any]]) -> List[str]:
    requested_room = _extract_requested_room(text) or _event_room(event_entry)
    if not requested_room:
        return [
            "Happy to outline the equipment — just let me know which room you have in mind.",
        ]
    features = list_room_features(requested_room)
    if not features:
        info = [f"{requested_room} offers Wi-Fi, daylight, and flexible seating as standard."]
    else:
        highlights = ", ".join(features[:6])
        info = [f"{requested_room} includes {highlights}."]
    return _with_preface(info, f"You were curious about {requested_room}, so here's a quick rundown:")


def _catering_response(
    text: str,
    event_entry: Optional[Dict[str, Any]],
) -> List[str]:
    room = _event_room(event_entry)
    date_token = _event_date_iso(event_entry)
    categories: Optional[List[str]] = None
    if "drink" in text.lower() or "beverage" in text.lower():
        categories = ["beverages"]
    options = list_catering(room_id=room, date_token=date_token, categories=categories)
    info: List[str] = []
    for entry in options[:4]:
        name = entry.get("name") or "Option"
        price = entry.get("price_per_person") or entry.get("price")
        descriptor = entry.get("description")
        price_text = f" — CHF {price}" if price else ""
        if categories == ["beverages"] and entry.get("options"):
            descriptor = ", ".join(entry["options"])
        if descriptor:
            info.append(f"{name}{price_text}: {descriptor}.")
        else:
            info.append(f"{name}{price_text}.")
    if not info:
        if room:
            info.append(f"I'll pull the detailed catering menus for {room} once we confirm the room and date.")
        else:
            info.append("Catering menus are available once we confirm the room/date combination.")
    if categories == ["beverages"]:
        preface = "Here are beverage pairings we can set up for you:"
    elif room and date_token:
        preface = f"Here are catering ideas that work well in {room} on your requested date:"
    elif room:
        preface = f"Here are catering ideas that work well in {room}:"
    else:
        preface = "Here are a few catering ideas we can arrange:"
    return _with_preface(info, preface)


def _products_response(
    event_entry: Optional[Dict[str, Any]],
) -> List[str]:
    room = _event_room(event_entry)
    items = list_products(room_id=room)
    info: List[str] = []
    for item in items[:4]:
        name = item.get("name")
        category = item.get("category")
        if category:
            info.append(f"{name} — {category.upper()} add-on.")
        else:
            info.append(f"{name}.")
    if not info:
        info.append("Add-on equipment menus unlock after we lock a room.")
    if room:
        preface = f"Here are some add-ons that pair nicely with {room}:"
    else:
        preface = "Here are the add-ons most teams choose:"
    return _with_preface(info, preface)


def _dates_response(
    text: str,
    event_entry: Optional[Dict[str, Any]],
    db: Optional[Dict[str, Any]],
) -> List[str]:
    anchor_month, anchor_day = _extract_anchor(text)
    preferred_room = _event_room(event_entry) or "Room A"
    dates = list_free_dates(anchor_month, anchor_day, count=5, db=db, preferred_room=preferred_room)
    info: List[str] = []
    for value in dates[:5]:
        info.append(f"{value} — {preferred_room} currently shows as free.")
    if not info:
        info.append("I can suggest dates once I have a preferred month or room.")
    preface: Optional[str] = None
    if anchor_month:
        try:
            month_name = datetime(2000, anchor_month, 1).strftime("%B")
        except ValueError:
            month_name = None
        if month_name and anchor_day:
            preface = f"Around {anchor_day} {month_name}, these slots are open in {preferred_room}:"
        elif month_name:
            preface = f"Here are a few {month_name} dates when {preferred_room} is available:"
    if not preface:
        preface = f"Here are upcoming dates when {preferred_room} is available:"
    return _with_preface(info, preface)


def _site_visit_response() -> List[str]:
    info = [
        "Site visits run Tuesday–Thursday between 10:00 and 18:00.",
        "We need a confirmed event date and time window before booking the tour.",
    ]
    return _with_preface(info, "Here's how site visits work at our venue:")


def _general_response(event_entry: Optional[Dict[str, Any]]) -> List[str]:
    step = _current_step(event_entry)
    if step == 2:
        return [
            "Once we pick a date I can check rooms and availability instantly.",
            "Rooms come with Wi-Fi, projector-ready HDMI, and daylight lighting.",
        ]
    if step == 3:
        return [
            "Rooms A–C include projectors and configurable seating.",
            "Tell me which room you prefer and I'll hold it while we build the offer.",
        ]
    return [
        "Happy to help with any venue questions — just let me know what you'd like to explore.",
    ]


def _parking_response() -> List[str]:
    info = [
        "Underground parking at Europaallee is two minutes from the venue with direct lift access.",
        "We can arrange a short-term loading permit for equipment drop-off with 24 hours' notice.",
    ]
    return _with_preface(info, "Thanks for checking on parking — here's what we can arrange nearby:")


def _step_index_from_anchor(anchor: Optional[str]) -> Optional[int]:
    if not anchor:
        return None
    lookup = {
        "date confirmation": 2,
        "room availability": 3,
        "offer review": 4,
        "site visit": 5,
        "follow-up": 7,
    }
    return lookup.get(anchor.strip().lower())


def _qna_target_step(qna_type: str) -> Optional[int]:
    mapping = {
        "free_dates": 2,
        "rooms_by_feature": 3,
        "room_features": 3,
        "catering_for": 4,
        "products_for": 4,
        "site_visit_overview": 5,
    }
    return mapping.get(qna_type)


def route_general_qna(
    msg: Dict[str, Any],
    event_entry_before: Optional[Dict[str, Any]],
    event_entry_after: Optional[Dict[str, Any]],
    db: Optional[Dict[str, Any]],
    classification: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Build deterministic INFO/NEXT STEP blocks for any general Q&A detected in the turn.
    """

    text = _message_text(msg)
    active_entry = event_entry_after or event_entry_before
    requirements = _event_requirements(active_entry)
    fallback_attendees = requirements.get("number_of_participants")
    attendees = _extract_attendees(text, fallback_attendees)
    layout = _extract_layout(text, requirements.get("seating_layout"))

    current_step = _current_step(active_entry)
    anchor_name = classification.get("step_anchor")
    anchor_step = _step_index_from_anchor(anchor_name)
    resume_step_idx = anchor_step or current_step
    missing = _missing_fields(resume_step_idx, active_entry)

    qna_types: List[str] = list(classification.get("secondary") or [])
    if not qna_types and classification.get("primary") == "general_qna":
        qna_types = ["general"]

    blocks_pre: List[Dict[str, Any]] = []
    blocks_post: List[Dict[str, Any]] = []

    for qna_type in qna_types:
        if qna_type == "general":
            info_lines = _general_response(active_entry)
            topic = "general_information"
            target_step_idx = resume_step_idx
        elif qna_type == "rooms_by_feature":
            info_lines = _rooms_by_feature_response(text, active_entry, attendees, layout)
            topic = "rooms_by_feature"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "room_features":
            info_lines = _room_features_response(text, active_entry)
            topic = "room_features"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "catering_for":
            info_lines = _catering_response(text, active_entry)
            topic = "catering_for"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "products_for":
            info_lines = _products_response(active_entry)
            topic = "products_for"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "free_dates":
            info_lines = _dates_response(text, active_entry, db)
            topic = "free_dates"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "site_visit_overview":
            info_lines = _site_visit_response()
            topic = "site_visit_overview"
            target_step_idx = _qna_target_step(qna_type) or resume_step_idx
        elif qna_type == "parking_policy":
            info_lines = _parking_response()
            topic = "parking_policy"
            target_step_idx = resume_step_idx
        else:
            info_lines = _general_response(active_entry)
            topic = "general_information"
            target_step_idx = resume_step_idx

        if current_step <= 1 and qna_type not in {"free_dates", "site_visit_overview"}:
            info_lines = _general_response(active_entry)
            topic = "general_information"
            target_step_idx = current_step

        info_block = build_info_block(info_lines)
        next_step_block = build_next_step_line(anchor_name or resume_step_idx, missing)
        body = "\n\n".join([info_block, next_step_block])

        block_payload = {
            "body": body,
            "topic": topic,
            "step": target_step_idx,
            "requires_approval": False,
        }

        target_anchor = _qna_target_step(qna_type)
        active_anchor = anchor_step or current_step
        destination = blocks_post
        if target_anchor is not None and target_anchor == active_anchor:
            destination = blocks_pre

        destination.append(block_payload)

    return {
        "pre_step": blocks_pre,
        "post_step": blocks_post,
        "resume_step": anchor_name or resume_step_idx,
        "missing_fields": missing,
        "status": (active_entry or {}).get("status"),
        "thread_state": (active_entry or {}).get("thread_state"),
    }


__all__ = ["route_general_qna"]
