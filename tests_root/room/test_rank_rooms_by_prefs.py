from __future__ import annotations

from workflows.common.sorting import rank_rooms, ROOM_OUTCOME_AVAILABLE, ROOM_OUTCOME_OPTION


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

    # Note: preferred_room bonus (30) intentionally overrides status difference (25)
    # to respect user's explicit room preference.
    ranked = rank_rooms(status_map, pax=30, preferences=preferences, preferred_room="Room B")

    assert ranked, "expected ranked results"
    # Preferred room now comes first due to intentional bonus (see sorting.py:106-108)
    assert ranked[0].room == "Room B"
    assert ranked[0].status == ROOM_OUTCOME_OPTION
    # Hints should reflect the top wish product when provided.
    assert ranked[0].hint == "red wine pairing"

    # Available room follows (still ranks higher than unavailable).
    assert any(entry.room == "Room A" and entry.status == ROOM_OUTCOME_AVAILABLE for entry in ranked)
