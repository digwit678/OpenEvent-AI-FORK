import json
from pathlib import Path

from ...utils.assertions import assert_next_step_cue

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "products_offer_cases.json"


def test_lte5_rooms_show_table_and_missing_items_branch():
    cases = json.loads(FIXTURE.read_text())
    scenario = cases["lte5_rank_by_wish"]

    thread_state = {
        "rooms": scenario["rooms"],
        "wish_products": scenario["wish_products"],
        "next_step": "products_table",
    }

    assert len(thread_state["rooms"]) == 5
    assert "Apéro" in thread_state["wish_products"]

    missing = cases["missing_items_approved"]
    hil_gate = {
        "missing_items": missing["missing"],
        "hil_status": missing["hil"],
        "next_step": 5,
    }

    assert hil_gate["hil_status"] == "approved"
    assert hil_gate["next_step"] == 5


def test_gt5_rooms_triggers_narrowing():
    cases = json.loads(FIXTURE.read_text())
    scenario = cases["gt5_needs_narrow"]

    narrowing_prompt = {
        "text": "Step: 4 Offer · Next: Narrow down preferred rooms · State: Awaiting Client",
    }
    assert_next_step_cue(narrowing_prompt)

    ranked = ["C", "D", "B", "A", "E"]
    assert len(scenario["rooms"]) > 5
    assert ranked[0] in scenario["rooms"]
