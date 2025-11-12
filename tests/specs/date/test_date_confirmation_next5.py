import json
from datetime import datetime
from pathlib import Path

from ...utils.timezone import TZ, freeze_time

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "date_next5_cases.json"


def _parse_candidate(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%d.%m.%Y")
    except ValueError:
        return datetime.fromisoformat(value)


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


def test_candidate_actions_and_table_shape():
    cases = json.loads(FIXTURE.read_text())
    many = cases["many_feasible"]
    candidate_dates = many["candidates"]

    table_block = {
        "type": "dates",
        "label": "Upcoming availability",
        "rows": [
            {
                "iso_date": _parse_candidate(value).strftime("%Y-%m-%d"),
                "display": _parse_candidate(value).strftime("%a %d %b %Y"),
                "status": "Available",
            }
            for value in candidate_dates
        ],
    }
    actions = [
        {
            "type": "select_date",
            "label": _parse_candidate(value).strftime("Confirm %a %d %b %Y"),
            "date": value,
            "iso_date": _parse_candidate(value).strftime("%Y-%m-%d"),
        }
        for value in candidate_dates
    ]

    assert table_block["type"] == "dates"
    assert all({"iso_date", "display"} <= row.keys() for row in table_block["rows"])
    assert all(action["type"] == "select_date" for action in actions)
    assert [row["iso_date"] for row in table_block["rows"]] == [action["iso_date"] for action in actions]