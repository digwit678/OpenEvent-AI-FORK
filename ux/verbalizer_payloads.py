"""
Facts bundle types for the Safety Sandwich LLM verbalizer.

These transient data structures capture the deterministic facts (rooms, menus, dates, prices)
that the LLM verbalizer may rephrase but must not alter or invent.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from workflows.common.sorting import RankedRoom
from workflows.common.types import WorkflowState


@dataclass
class RoomFact:
    """Immutable room fact for verbalization."""

    name: str
    status: str  # Available | Option | Unavailable
    capacity_max: Optional[int] = None
    capacity_min: Optional[int] = None
    features: List[str] = field(default_factory=list)
    matched_preferences: List[str] = field(default_factory=list)
    missing_preferences: List[str] = field(default_factory=list)
    hint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "capacity_max": self.capacity_max,
            "capacity_min": self.capacity_min,
            "features": self.features,
            "matched_preferences": self.matched_preferences,
            "missing_preferences": self.missing_preferences,
            "hint": self.hint,
        }


@dataclass
class MenuFact:
    """Immutable menu fact for verbalization."""

    name: str
    price: str  # Formatted string, e.g. "CHF 92"
    price_numeric: Optional[float] = None
    courses: Optional[int] = None
    description: Optional[str] = None
    vegetarian: bool = False
    wine_pairing: bool = False
    season_label: Optional[str] = None
    notes: List[str] = field(default_factory=list)
    applicable_rooms: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "price": self.price,
            "price_numeric": self.price_numeric,
            "courses": self.courses,
            "description": self.description,
            "vegetarian": self.vegetarian,
            "wine_pairing": self.wine_pairing,
            "season_label": self.season_label,
            "notes": self.notes,
            "applicable_rooms": self.applicable_rooms,
        }


@dataclass
class RoomOfferFacts:
    """
    Facts bundle for room/offer verbalization.

    Contains all deterministic facts that must be preserved by the LLM verbalizer.
    The verifier will check that these facts appear unchanged in the LLM output.
    """

    # Event context
    event_date: str  # Canonical format: DD.MM.YYYY
    event_date_iso: Optional[str] = None  # ISO format: YYYY-MM-DD
    participants_count: Optional[int] = None
    time_window: Optional[str] = None  # e.g., "14:00–18:00"

    # Rooms
    rooms: List[RoomFact] = field(default_factory=list)
    recommended_room: Optional[str] = None

    # Menus
    menus: List[MenuFact] = field(default_factory=list)

    # Totals (if already calculated)
    total_amount: Optional[str] = None  # Formatted, e.g. "CHF 500"
    total_amount_numeric: Optional[float] = None
    deposit_amount: Optional[str] = None
    deposit_amount_numeric: Optional[float] = None

    # Step context
    current_step: Optional[int] = None
    status: Optional[str] = None  # Lead | Option | Confirmed

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for JSON serialization to LLM."""
        return {
            "event_date": self.event_date,
            "event_date_iso": self.event_date_iso,
            "participants_count": self.participants_count,
            "time_window": self.time_window,
            "rooms": [r.to_dict() for r in self.rooms],
            "recommended_room": self.recommended_room,
            "menus": [m.to_dict() for m in self.menus],
            "total_amount": self.total_amount,
            "total_amount_numeric": self.total_amount_numeric,
            "deposit_amount": self.deposit_amount,
            "deposit_amount_numeric": self.deposit_amount_numeric,
            "current_step": self.current_step,
            "status": self.status,
        }


def build_room_offer_facts(
    state: WorkflowState,
    ranked_rooms: Optional[List[RankedRoom]] = None,
    menus: Optional[List[Dict[str, Any]]] = None,
    room_profiles: Optional[Dict[str, Dict[str, Any]]] = None,
) -> RoomOfferFacts:
    """
    Build a RoomOfferFacts bundle from workflow state.

    This is a pure function that extracts and reformats existing data.
    It does not add new business logic or make decisions.
    """
    event_entry = state.event_entry or {}
    requirements = event_entry.get("requirements") or {}

    # Extract date
    chosen_date = event_entry.get("chosen_date") or ""
    event_date_iso = None
    if chosen_date:
        # If it's already DD.MM.YYYY, keep it; if ISO, convert
        if len(chosen_date) == 10 and chosen_date[4] == "-":
            event_date_iso = chosen_date
            # Convert ISO to DD.MM.YYYY
            parts = chosen_date.split("-")
            if len(parts) == 3:
                chosen_date = f"{parts[2]}.{parts[1]}.{parts[0]}"
        elif len(chosen_date) == 10 and chosen_date[2] == ".":
            # Already DD.MM.YYYY, derive ISO
            parts = chosen_date.split(".")
            if len(parts) == 3:
                event_date_iso = f"{parts[2]}-{parts[1]}-{parts[0]}"

    # Extract participants
    participants = requirements.get("number_of_participants") or requirements.get("participants")
    if isinstance(participants, str):
        try:
            participants = int(participants)
        except ValueError:
            participants = None

    # Extract time window
    time_start = event_entry.get("time_start") or requirements.get("start_time")
    time_end = event_entry.get("time_end") or requirements.get("end_time")
    time_window = None
    if time_start and time_end:
        time_window = f"{time_start}–{time_end}"
    elif time_start:
        time_window = f"from {time_start}"

    # Build room facts
    room_facts: List[RoomFact] = []
    recommended = None

    if ranked_rooms:
        for idx, ranked in enumerate(ranked_rooms):
            profile = (room_profiles or {}).get(ranked.room, {})
            room_fact = RoomFact(
                name=ranked.room,
                status=ranked.status,
                capacity_max=profile.get("capacity_max"),
                capacity_min=profile.get("capacity_min"),
                features=profile.get("features", []),
                matched_preferences=ranked.matched,
                missing_preferences=ranked.missing,
                hint=ranked.hint if ranked.hint else None,
            )
            room_facts.append(room_fact)
            # First available or option room is recommended
            if recommended is None and ranked.status in ("Available", "Option"):
                recommended = ranked.room

    # Build menu facts
    menu_facts: List[MenuFact] = []
    if menus:
        for menu in menus:
            price_str = menu.get("price", "")
            price_numeric = None
            if price_str:
                # Extract numeric value from "CHF 92"
                import re
                match = re.search(r"[\d.]+", price_str)
                if match:
                    try:
                        price_numeric = float(match.group())
                    except ValueError:
                        pass

            menu_fact = MenuFact(
                name=menu.get("menu_name", ""),
                price=price_str,
                price_numeric=price_numeric,
                courses=menu.get("courses"),
                description=menu.get("description"),
                vegetarian=menu.get("vegetarian", False),
                wine_pairing=menu.get("wine_pairing", False),
                season_label=menu.get("season_label"),
                notes=menu.get("notes", []),
                applicable_rooms=menu.get("applicable_rooms", []),
            )
            menu_facts.append(menu_fact)

    # Extract totals if present
    offers = event_entry.get("offers") or []
    total_amount = None
    total_numeric = None
    deposit_amount = None
    deposit_numeric = None

    if offers:
        latest_offer = offers[-1] if offers else {}
        total_val = latest_offer.get("total_amount")
        if total_val is not None:
            if isinstance(total_val, (int, float)):
                total_numeric = float(total_val)
                total_amount = f"CHF {total_val:.2f}" if total_val else None
            elif isinstance(total_val, str):
                total_amount = total_val

        deposit_val = latest_offer.get("deposit_amount")
        if deposit_val is not None:
            if isinstance(deposit_val, (int, float)):
                deposit_numeric = float(deposit_val)
                deposit_amount = f"CHF {deposit_val:.2f}" if deposit_val else None
            elif isinstance(deposit_val, str):
                deposit_amount = deposit_val

    return RoomOfferFacts(
        event_date=chosen_date,
        event_date_iso=event_date_iso,
        participants_count=participants,
        time_window=time_window,
        rooms=room_facts,
        recommended_room=recommended,
        menus=menu_facts,
        total_amount=total_amount,
        total_amount_numeric=total_numeric,
        deposit_amount=deposit_amount,
        deposit_amount_numeric=deposit_numeric,
        current_step=state.current_step,
        status=event_entry.get("metadata", {}).get("status") or event_entry.get("status") or "Lead",
    )


__all__ = [
    "RoomFact",
    "MenuFact",
    "RoomOfferFacts",
    "build_room_offer_facts",
]
