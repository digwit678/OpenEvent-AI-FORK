from __future__ import annotations

from datetime import date

from workflows.io import dates


def _reset_blackouts(monkeypatch, blocked):
    monkeypatch.setattr(dates, "blackout_days", lambda: set(blocked))


def test_next5_honours_weekday_preference(monkeypatch):
    _reset_blackouts(monkeypatch, set())
    base = date(2025, 1, 1)

    results = dates.next5(base, {"weekday": "Saturday", "days_ahead": 120})

    assert len(results) == 5
    assert all(result >= base for result in results)
    assert all(result.weekday() == 5 for result in results)


def test_next5_skips_blackout_windows(monkeypatch):
    blocked = {date(2025, 1, 4), date(2025, 1, 11)}
    _reset_blackouts(monkeypatch, blocked)
    base = date(2025, 1, 1)

    results = dates.next5(base, {"weekday": "Saturday", "days_ahead": 90})

    assert len(results) == 5
    assert all(result not in blocked for result in results)
    assert all(result.weekday() == 5 for result in results[:3])


def test_next5_falls_back_when_window_exhausted(monkeypatch):
    _reset_blackouts(monkeypatch, set())
    base = date(2025, 12, 20)

    results = dates.next5(base, {"month": "December", "weekday": "Sunday", "days_ahead": 10})

    assert len(results) == 5
    primary = [result for result in results if result.month == 12 and result.weekday() == 6]
    assert len(primary) < 5  # fallback injected additional dates
    assert results == sorted(results)