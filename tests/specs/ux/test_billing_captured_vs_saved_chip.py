from __future__ import annotations

from backend.debug.hooks import trace_state
from backend.debug.trace import BUS


def test_billing_tracked_info(monkeypatch):
    monkeypatch.setenv("DEBUG_TRACE", "1")
    BUS._buf.clear()  # type: ignore[attr-defined]
    thread_id = "billing-info-thread"

    trace_state(
        thread_id,
        "Step4_Offer",
        {
            "event_data": {"Billing Address": "Pixel Forge GmbH, Samplestrasse 1, 8000 Zürich"},
        },
    )
    events = BUS.get(thread_id)  # type: ignore[attr-defined]
    first_snapshot = next(event for event in events if event.get("kind") == "STATE_SNAPSHOT")
    tracked = first_snapshot.get("data", {}).get("tracked_info", {})
    assert tracked.get("billing_address_captured_raw", "").startswith("Pixel Forge")

    trace_state(
        thread_id,
        "Step4_Offer",
        {
            "event_data": {"Billing Address": "Pixel Forge GmbH"},
            "billing_details": {
                "name_or_company": "Pixel Forge GmbH",
                "street": "Samplestrasse 1",
                "postal_code": "8000",
                "city": "Zürich",
                "country": "Switzerland",
            },
        },
    )
    events = BUS.get(thread_id)  # type: ignore[attr-defined]
    latest_snapshot = [event for event in events if event.get("kind") == "STATE_SNAPSHOT"][-1]
    tracked_latest = latest_snapshot.get("data", {}).get("tracked_info", {})
    assert tracked_latest.get("billing_address_saved") is True
    assert "billing_address_captured_raw" not in tracked_latest

    BUS._buf.clear()  # type: ignore[attr-defined]
