from __future__ import annotations

from workflows.qna.verbalizer import render_qna_answer


def test_verbalizer_fallback_formats_rooms_products():
    payload = {
        "qna_intent": "select_dependent",
        "qna_subtype": "room_list_for_us",
        "effective": {},
        "db_results": {
            "rooms": [
                {"room_name": "Room A", "capacity_max": 60, "status": "available"},
                {"room_name": "Room B", "capacity_max": 80, "status": "available"},
            ],
            "products": [
                {"product": "Vegan Lunch", "available_today": True},
                {"product": "Prosecco Bar", "available_today": False},
            ],
            "dates": [],
            "notes": [],
        },
    }
    output = render_qna_answer(payload)
    assert "Room A" in output["body_markdown"]
    assert "Vegan Lunch" in output["body_markdown"]
