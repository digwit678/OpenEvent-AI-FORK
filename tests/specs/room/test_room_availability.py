import json
from hashlib import sha256
from pathlib import Path

from ...utils.seeds import set_seed

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "room_search_cases.json"


def _requirements_hash(requirements: dict) -> str:
    payload = f"{requirements['date']}|{requirements['capacity']}|{requirements['layout']}"
    return sha256(payload.encode()).hexdigest()


def test_room_search_classification():
    cases = json.loads(FIXTURE.read_text())

    available = cases["available"]
    option_only = cases["option_only"]
    unavailable = cases["unavailable"]

    assert any(room["fits"] and not room["option"] for room in available["rooms"])
    assert all(room["option"] for room in option_only["rooms"])
    assert unavailable["rooms"] == []


def test_lock_room_records_hash():
    set_seed()
    case = json.loads(FIXTURE.read_text())["available"]

    requirements = {
        "date": case["date"],
        "capacity": case["capacity"],
        "layout": "theatre",
    }

    locked_room_id = case["rooms"][0]["id"]
    requirements_hash = _requirements_hash(requirements)
    room_eval_hash = requirements_hash

    lock_payload = {
        "locked_room_id": locked_room_id,
        "room_eval_hash": room_eval_hash,
        "next_step": 4,
    }

    assert lock_payload["locked_room_id"] == "R1"
    assert lock_payload["room_eval_hash"] == requirements_hash
    assert lock_payload["next_step"] == 4
