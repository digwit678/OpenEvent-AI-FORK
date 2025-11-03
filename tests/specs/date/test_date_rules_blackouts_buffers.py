import json
from datetime import date, timedelta
from pathlib import Path

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "blackout_buffer_windows.json"


def _expand_buffers(target: date, window: dict) -> set[date]:
    before = {target - timedelta(days=i) for i in range(0, window["days_before"] + 1)}
    after = {target + timedelta(days=i) for i in range(0, window["days_after"] + 1)}
    return before | after


def test_blackout_and_buffers_remove_dates():
    config = json.loads(FIXTURE.read_text())
    blackouts = {date.fromisoformat(day) for day in config["blackouts"]}
    buffers = config["buffers"]

    proposed = {date(2025, 11, 9), date(2025, 11, 10), date(2025, 11, 12), date(2025, 12, 24)}

    invalid = set()
    for blocked in blackouts:
        invalid |= _expand_buffers(blocked, buffers[0])

    feasible = sorted(proposed - invalid)
    assert date(2025, 11, 12) in feasible
    assert date(2025, 11, 9) not in feasible
    assert date(2025, 11, 10) not in feasible
    assert date(2025, 12, 24) not in feasible
