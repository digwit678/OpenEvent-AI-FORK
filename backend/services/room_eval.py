from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from backend.services.availability import calendar_free
from backend.services.products import check_availability
from backend.services.rooms import RoomRecord, load_room_catalog

STATUS_ORDER = {"Available": 0, "Option": 1, "Unavailable": 2}


@dataclass
class RoomEvaluation:
    record: RoomRecord
    status: str
    coverage_matched: int
    coverage_total: int
    matched_features: List[str]
    missing_features: List[str]
    capacity_slack: Optional[int]
    reasons: List[str]
    available_products: List[Dict[str, Any]] = field(default_factory=list)
    missing_products: List[Dict[str, Any]] = field(default_factory=list)

    def to_payload(self) -> Dict[str, Any]:
        return {
            "room": self.record.name,
            "status": self.status,
            "coverage_matched": self.coverage_matched,
            "coverage_total": self.coverage_total,
            "matched_features": self.matched_features,
            "missing_features": self.missing_features,
            "capacity_slack": self.capacity_slack,
            "reasons": self.reasons,
            "available_products": self.available_products,
            "missing_products": self.missing_products,
        }


def evaluate_rooms(event_entry: Dict[str, Any], requested_products: Optional[List[Dict[str, Any]]] = None) -> List[RoomEvaluation]:
    requirements = event_entry.get("requirements") or {}
    participants = _safe_int(requirements.get("number_of_participants"))
    layout = str(requirements.get("seating_layout") or "").strip().lower()
    requested_features = _extract_requested_features(requirements)
    window = event_entry.get("requested_window") or {}
    requested = requested_products or event_entry.get("requested_products") or []

    evaluations: List[RoomEvaluation] = []
    for record in load_room_catalog():
        available = calendar_free(record.name, window)
        capacity_ok, slack, capacity_reason = _check_capacity(record, participants, layout)

        matched, missing = _feature_coverage(record.features, requested_features)
        availability = check_availability(requested, record.room_id, window.get("date_iso"))
        available_products = availability.get("available", []) if availability else []
        missing_products = availability.get("missing", []) if availability else []

        reasons: List[str] = []
        if not available:
            reasons.append("Another event overlaps this time.")
        if not capacity_ok and capacity_reason:
            reasons.append(capacity_reason)
        if missing:
            missing_human = ", ".join(_humanize_feature(f) for f in missing)
            reasons.append(f"Missing: {missing_human}")

        if available and capacity_ok:
            status = "Available"
        elif capacity_ok:
            status = "Option"
        else:
            status = "Unavailable"

        evaluations.append(
            RoomEvaluation(
                record=record,
                status=status,
                coverage_matched=len(matched),
                coverage_total=len(requested_features),
                matched_features=[_humanize_feature(f) for f in matched],
                missing_features=[_humanize_feature(f) for f in missing],
                capacity_slack=slack,
                reasons=reasons,
                available_products=available_products,
                missing_products=missing_products,
            )
        )
    return evaluations


def rank_rooms(evaluations: Iterable[RoomEvaluation]) -> List[RoomEvaluation]:
    def sort_key(entry: RoomEvaluation) -> Tuple[int, int, int, str]:
        status_rank = STATUS_ORDER.get(entry.status, 99)
        coverage_rank = -entry.coverage_matched
        slack = entry.capacity_slack if entry.capacity_slack is not None else 9999
        return (status_rank, coverage_rank, slack, entry.record.name.lower())

    return sorted(list(evaluations), key=sort_key)


def _check_capacity(
    record: RoomRecord,
    participants: Optional[int],
    layout: str,
) -> Tuple[bool, Optional[int], Optional[str]]:
    if participants is None or participants <= 0:
        return True, None, None

    layout_key = layout.replace(" ", "_")
    layout_capacity = record.capacity_by_layout.get(layout_key)
    capacity = layout_capacity or record.capacity_max

    if capacity is None:
        return True, None, None
    slack = capacity - participants
    if slack < 0:
        return False, slack, f"Seats up to {capacity} guests in this layout."
    return True, slack, None


def _extract_requested_features(requirements: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []
    notes = [
        str(requirements.get("special_requirements") or ""),
        str(requirements.get("notes") or ""),
    ]
    combined = " ".join(notes).lower()
    feature_keywords = {
        "stage": ["stage", "podium"],
        "screen": ["screen", "projector screen"],
        "projector": ["projector", "beam"],
        "parking": ["parking", "parking spots"],
        "sound_system": ["sound system", "pa", "speaker"],
        "hybrid": ["hybrid", "stream"],
    }
    for feature, keywords in feature_keywords.items():
        if any(keyword in combined for keyword in keywords):
            tokens.append(feature)
    return tokens


def _feature_coverage(
    room_features: List[str],
    requested: List[str],
) -> Tuple[List[str], List[str]]:
    room_set = {feature.strip().lower() for feature in room_features}
    matched: List[str] = []
    missing: List[str] = []
    for feature in requested:
        if feature in room_set:
            matched.append(feature)
        else:
            missing.append(feature)
    return matched, missing


def _humanize_feature(feature: str) -> str:
    mapping = {
        "sound_system": "Sound system",
        "projector": "Projector",
        "screen": "Screen",
        "parking": "Parking nearby",
        "stage": "Stage",
        "hybrid": "Hybrid setup",
    }
    return mapping.get(feature, feature.replace("_", " ").title())


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
