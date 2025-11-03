import json
from datetime import datetime
from pathlib import Path

from ...utils.timezone import TZ, freeze_time

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "date_next5_cases.json"


def _classify(feasible_count: int) -> str:
    if feasible_count == 0:
        return "refresh"
    if feasible_count == 1:
        return "confirm"
    return "disambiguate"


def test_next5_classifications_cover_all_branches():
    cases = json.loads(FIXTURE.read_text())

    with freeze_time(cases["none_feasible"]["today"]):
        assert _classify(len(cases["none_feasible"]["feasible"])) == "refresh"

    with freeze_time(cases["one_feasible"]["today"]):
        assert _classify(len(cases["one_feasible"]["feasible"])) == "confirm"

    with freeze_time(cases["many_feasible"]["today"]):
        assert _classify(len(cases["many_feasible"]["feasible"])) == "disambiguate"


def test_confirm_sets_chosen_date_and_flag():
    cases = json.loads(FIXTURE.read_text())
    single = cases["one_feasible"]

    with freeze_time(single["today"]):
        chosen = single["feasible"][0]
        thread_state = {
            "chosen_date": chosen,
            "date_confirmed": True,
            "presented_candidates": single["candidates"],
            "timezone": TZ,
        }

    assert datetime.fromisoformat(thread_state["chosen_date"])
    assert thread_state["date_confirmed"] is True
    assert thread_state["timezone"] == TZ
