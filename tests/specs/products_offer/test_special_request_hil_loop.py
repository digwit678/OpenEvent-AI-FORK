import json
from pathlib import Path

from ...utils.assertions import assert_wait_state

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "special_request_cases.json"


def test_special_request_waits_for_hil():
    cases = json.loads(FIXTURE.read_text())
    approve = cases["approve_all"]

    hil_state = {"thread_state": "Waiting on HIL", "items": approve["items"], "decision": None}
    assert_wait_state(hil_state, "Waiting on HIL")

    hil_state["decision"] = approve["decision"]
    assert hil_state["decision"] == "approved"


def test_denied_request_recommends_alternative():
    cases = json.loads(FIXTURE.read_text())
    deny = cases["deny_partial"]

    alt_response = {
        "footer": "Step: 4 Offer · Next: Review alternatives · State: Awaiting Client",
        "recommendations": ["Partner café"],
        "decision": deny["decision"],
    }

    assert alt_response["decision"] == "denied"
    assert "alternatives" in alt_response["footer"].lower()
