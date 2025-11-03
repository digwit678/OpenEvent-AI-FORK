from hashlib import sha256


def _hash(requirements: dict) -> str:
    payload = "|".join(str(requirements[k]) for k in sorted(requirements))
    return sha256(payload.encode()).hexdigest()


def test_guard_recomputes_only_on_hash_change():
    base_requirements = {"capacity": 80, "date": "2025-11-12", "layout": "banquet"}
    stale_eval = {"room_eval_hash": _hash(base_requirements), "locked_room_id": "R5"}

    # Changing layout should force recompute
    mutated = {**base_requirements, "layout": "theatre"}
    assert _hash(mutated) != stale_eval["room_eval_hash"]

    # Keeping requirements but changing date within same constraints keeps fast-path
    new_date = {**base_requirements, "date": "2025-11-13"}
    fast_path = _hash(new_date) == stale_eval["room_eval_hash"]

    assert fast_path is False


def test_date_change_fast_path_when_hash_matches():
    locked = {
        "locked_room_id": "R2",
        "requirements_hash": _hash({"capacity": 50, "date": "2025-11-12", "layout": "u-shape"}),
    }

    detour_payload = {
        "caller_step": 4,
        "new_date": "2025-11-12",
        "recomputed_hash": locked["requirements_hash"],
    }

    assert detour_payload["caller_step"] == 4
    assert detour_payload["recomputed_hash"] == locked["requirements_hash"]
