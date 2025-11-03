PREREQS = {
    "P1": "Intake complete",
    "P2": "Date confirmed",
    "P3": "Room locked",
    "P4": "Products curated",
}


def test_prerequisites_gate_step_four():
    state = {"step": 4, "met": {"P1", "P2", "P3", "P4"}}
    assert state["met"] == set(PREREQS)

    missing_state = {"step": 4, "met": {"P1", "P2"}}
    unmet = set(PREREQS) - missing_state["met"]
    assert unmet == {"P3", "P4"}

    detour = {"target": 3 if "P3" in unmet else 2}
    assert detour["target"] == 3
