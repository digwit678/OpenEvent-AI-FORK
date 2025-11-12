from __future__ import annotations

from backend.workflows.common.sorting import rank_rooms, ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION


def test_rank_rooms_by_preferences_prioritises_available_and_hints():
    status_map = {
        "Room A": ROOM_OUTCOME_AVAILABLE,
        "Room B": ROOM_OUTCOME_OPTION,
        "Room C": "Unavailable",
    }
    preferences = {
        "wish_products": ["red wine pairing"],
        "keywords": ["long table"],
    }

    ranked = rank_rooms(status_map, pax=30, preferences=preferences, preferred_room="Room B")

    assert ranked, "expected ranked results"
    # Available room should come first even if another room is preferred.
    assert ranked[0].room == "Room A"
    assert ranked[0].status == ROOM_OUTCOME_AVAILABLE
    # Hints should reflect the top wish product when provided.
    assert ranked[0].hint == "red wine pairing"

    # Option room should follow next.
    assert any(entry.room == "Room B" for entry in ranked)
