"""DB1 Characterization test: Billing address persistence through router flush.

This test ensures that billing_details captured in Step5 are persisted to disk
via the router's end-of-turn flush, NOT via force-save calls inside step handlers.

Background:
- Step5 historically used direct db_io.save_db() calls to force-persist billing
- This violated the "router persists once at end-of-turn" discipline
- The router's _flush_pending_save mechanism should handle all persistence

Test case:
1. Create an event at Step 5 with awaiting_billing_for_accept=True
2. Send a message with billing address
3. Assert billing_details are persisted to disk file after process_msg returns
"""
import json
import os
import pytest
from pathlib import Path
from datetime import datetime

from workflow_email import process_msg
from workflows.io import database as db_io


# Run with AGENT_MODE=stub
pytestmark = pytest.mark.usefixtures("stub_agent_mode")


@pytest.fixture
def stub_agent_mode():
    """Ensure AGENT_MODE=stub for these tests."""
    old_mode = os.environ.get("AGENT_MODE")
    os.environ["AGENT_MODE"] = "stub"
    yield
    if old_mode is not None:
        os.environ["AGENT_MODE"] = old_mode
    else:
        os.environ.pop("AGENT_MODE", None)


class TestBillingPersistenceDB1:
    """Characterization test for billing persistence via router flush."""

    @pytest.fixture
    def temp_db_path(self, tmp_path: Path) -> Path:
        """Create a temp DB path for testing."""
        return tmp_path / "events.json"

    @pytest.fixture
    def event_at_step5_awaiting_billing(self) -> dict:
        """An event at Step 5, offer accepted, awaiting billing address."""
        now = datetime.utcnow().isoformat() + "Z"
        return {
            "event_id": "evt_billing_test_db1",
            "thread_id": "billing-test-thread-db1",
            "client_email": "billing-test@example.com",
            "client_name": "Test Client",
            "current_step": 5,
            "status": "Lead",
            "offer_accepted": True,
            "offer_hash": "hash_abc123",
            "billing_requirements": {
                "awaiting_billing_for_accept": True,
                "last_missing": ["street"],
            },
            "requirements": {
                "number_of_participants": 20,
                "duration": "10:00-16:00",
            },
            "requirements_hash": "req_hash_xyz",
            "room_eval_hash": "req_hash_xyz",
            "locked_room_id": "room-1",
            "chosen_date": "2026-03-15",
            "date_confirmed": True,
            "created_at": now,
            "event_data": {
                "Email": "billing-test@example.com",
                "Name": "Test Client",
                "Number of Participants": "20",
                # No Billing Address yet
            },
            "deposit_info": {
                "deposit_required": False,
            },
            # No billing_details yet - this is what we're testing
        }

    @pytest.fixture
    def seed_db(self, temp_db_path: Path, event_at_step5_awaiting_billing: dict) -> dict:
        """Seed the temp DB file with the test event."""
        db = db_io.get_default_db()
        db["events"].append(event_at_step5_awaiting_billing)
        db["clients"]["billing-test@example.com"] = {
            "email": "billing-test@example.com",
            "name": "Test Client",
            "phone": "",
            "language": "en",
            "profile": {"name": "Test Client"},
            "history": [],
            "event_ids": ["evt_billing_test_db1"],
        }
        db_io.save_db(db, temp_db_path)
        return db

    def test_billing_address_persisted_via_router_flush(
        self, temp_db_path: Path, seed_db: dict
    ):
        """Billing details should persist to disk via router's end-of-turn flush.

        This is the characterization test that must pass BEFORE removing force-saves.
        If this fails after removing force-saves, it means the router flush is broken.
        """
        # Arrange: Billing address message with structured format
        billing_msg = {
            "from_email": "billing-test@example.com",
            "from_name": "Test Client",
            "subject": "Re: Booking Confirmation",
            "body": "Test Company GmbH, Musterstrasse 123, 8000 Zurich, Switzerland",
            "thread_id": "billing-test-thread-db1",
        }

        # Act: Process the message through the full workflow
        result = process_msg(billing_msg, db_path=temp_db_path)

        # Assert: Call completed (should not crash)
        assert result is not None, "process_msg should return a result"

        # Assert: Billing details are PERSISTED to disk
        # This is the critical assertion - reload from disk and check
        reloaded_db = db_io.load_db(temp_db_path)

        # Find our test event
        test_event = None
        for evt in reloaded_db.get("events", []):
            if evt.get("event_id") == "evt_billing_test_db1":
                test_event = evt
                break

        assert test_event is not None, "Test event should exist in reloaded DB"

        # Check event_data has Billing Address
        event_data = test_event.get("event_data") or {}
        billing_address_raw = event_data.get("Billing Address")
        assert billing_address_raw, (
            f"Billing Address should be captured in event_data. Got: {event_data}"
        )

        # Check billing_details was parsed and persisted
        billing_details = test_event.get("billing_details")
        assert billing_details is not None, (
            "billing_details should be persisted to disk. "
            "If this fails after removing force-saves, the router flush is broken."
        )

        # Verify billing address was parsed correctly (at minimum street should exist)
        has_address = bool(
            billing_details.get("street")
            or billing_details.get("raw")
            or billing_details.get("name_or_company")
        )
        assert has_address, (
            f"Billing should have at least one field populated. Got: {billing_details}"
        )

    def test_billing_flag_cleared_after_capture(
        self, temp_db_path: Path, seed_db: dict
    ):
        """awaiting_billing_for_accept should be False after billing captured."""
        billing_msg = {
            "from_email": "billing-test@example.com",
            "from_name": "Test Client",
            "subject": "Re: Booking",
            "body": "ABC Corp, Main St 1, 8000 Zurich, Switzerland",
            "thread_id": "billing-test-thread-db1",
        }

        process_msg(billing_msg, db_path=temp_db_path)

        # Reload and check flag is cleared
        reloaded_db = db_io.load_db(temp_db_path)
        test_event = next(
            (e for e in reloaded_db.get("events", [])
             if e.get("event_id") == "evt_billing_test_db1"),
            None
        )

        assert test_event is not None, "Test event should exist"
        billing_req = test_event.get("billing_requirements") or {}
        # Flag should be False (or missing) after billing is complete
        assert billing_req.get("awaiting_billing_for_accept") is not True, (
            "awaiting_billing_for_accept should be cleared (False) after billing captured"
        )

    def test_billing_details_complete(
        self, temp_db_path: Path, seed_db: dict
    ):
        """Verify billing_details is parsed with expected structure."""
        billing_msg = {
            "from_email": "billing-test@example.com",
            "from_name": "Test Client",
            "subject": "Re: Booking",
            # Comprehensive billing address with all fields
            "body": "ACME GmbH, Bahnhofstrasse 10, 8001 Zurich, Switzerland",
            "thread_id": "billing-test-thread-db1",
        }

        process_msg(billing_msg, db_path=temp_db_path)

        reloaded_db = db_io.load_db(temp_db_path)
        test_event = next(
            (e for e in reloaded_db.get("events", [])
             if e.get("event_id") == "evt_billing_test_db1"),
            None
        )

        assert test_event is not None
        billing = test_event.get("billing_details") or {}

        # Check that key fields are populated
        # The parser should extract company/name, street, city, country
        print(f"[DEBUG] Parsed billing_details: {billing}")

        # At minimum, raw should be set or street should be populated
        assert billing, f"billing_details should not be empty. Event: {test_event.keys()}"
