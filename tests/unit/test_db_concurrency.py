"""
Test: Database concurrency behavior (F-02 finding)

This test documents the race condition in JSON database updates:
- The FileLock only wraps individual I/O operations (load/save)
- It does NOT wrap the entire "load → process → save" transaction
- Concurrent workers can load the same snapshot and overwrite each other

This is an INFORMATIONAL test - it documents known behavior, not a regression guard.
When the underlying concurrency issue is fixed, this test should be updated.
"""

import json
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, Any, List

import pytest

from workflows.io.database import load_db, save_db


@pytest.mark.v4
def test_concurrent_updates_can_lose_data():
    """
    Demonstrate that concurrent load→modify→save cycles can lose updates.

    Scenario:
    - Worker A loads DB, adds event "A"
    - Worker B loads DB (same snapshot), adds event "B"
    - Worker A saves → DB has event "A"
    - Worker B saves → DB has only event "B" (A's update is lost!)

    This test PASSES when data loss occurs (documenting the current behavior).
    When the bug is fixed, this test should FAIL and be rewritten.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_db.json"

        # Initialize empty DB
        initial_db = {"events": [], "clients": {}, "tasks": []}
        with open(db_path, "w") as f:
            json.dump(initial_db, f)

        results: Dict[str, Any] = {"a_loaded": False, "b_loaded": False}
        barrier = threading.Barrier(2)  # Sync both workers

        def worker_a():
            # Load DB
            db = load_db(db_path)
            results["a_loaded"] = True

            # Wait for B to also load (both have same snapshot)
            barrier.wait()

            # Add event A
            db["events"].append({"event_id": "event-A", "name": "Event A"})

            # Small delay to let B modify its copy
            time.sleep(0.05)

            # Save
            save_db(db, db_path)

        def worker_b():
            # Load DB
            db = load_db(db_path)
            results["b_loaded"] = True

            # Wait for A to also load
            barrier.wait()

            # Add event B
            db["events"].append({"event_id": "event-B", "name": "Event B"})

            # Delay to ensure A saves first
            time.sleep(0.1)

            # Save (this overwrites A's changes)
            save_db(db, db_path)

        # Run both workers concurrently
        thread_a = threading.Thread(target=worker_a)
        thread_b = threading.Thread(target=worker_b)

        thread_a.start()
        thread_b.start()

        thread_a.join(timeout=5)
        thread_b.join(timeout=5)

        # Load final state
        final_db = load_db(db_path)
        event_ids = [e["event_id"] for e in final_db.get("events", [])]

        # Document the race condition: B's save overwrites A's changes
        # Expected (if bug exists): only event-B is present
        # Expected (if bug fixed): both event-A and event-B are present

        if "event-A" in event_ids and "event-B" in event_ids:
            pytest.fail(
                "GOOD NEWS: Both events preserved! The concurrency bug may be fixed. "
                "Update this test to be a regression guard."
            )
        else:
            # This documents the current buggy behavior
            assert "event-B" in event_ids, "Event B should be present (last writer wins)"
            assert "event-A" not in event_ids, (
                "Event A is lost due to race condition (F-02). "
                "This test documents the known behavior."
            )


@pytest.mark.v4
def test_sequential_updates_preserve_data():
    """
    Verify that sequential (non-concurrent) updates work correctly.

    This is a sanity check - when operations don't overlap, data is preserved.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_db.json"

        # Initialize empty DB
        initial_db = {"events": [], "clients": {}, "tasks": []}
        with open(db_path, "w") as f:
            json.dump(initial_db, f)

        # Sequential operations
        db1 = load_db(db_path)
        db1["events"].append({"event_id": "event-1"})
        save_db(db1, db_path)

        db2 = load_db(db_path)
        db2["events"].append({"event_id": "event-2"})
        save_db(db2, db_path)

        db3 = load_db(db_path)
        db3["events"].append({"event_id": "event-3"})
        save_db(db3, db_path)

        # Verify all events are preserved
        final_db = load_db(db_path)
        event_ids = [e["event_id"] for e in final_db.get("events", [])]

        assert "event-1" in event_ids
        assert "event-2" in event_ids
        assert "event-3" in event_ids
        assert len(event_ids) == 3
