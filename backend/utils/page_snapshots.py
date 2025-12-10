"""
Snapshot storage for info page data.

When the workflow generates detailed data (rooms, products, etc.) for display,
we store a snapshot so that:
1. The info page link stays valid even as workflow progresses
2. Client can revisit older links in the conversation
3. Same data source as verbalizer ensures consistency

Snapshots are stored in a JSON file with TTL-based expiration.
"""

from __future__ import annotations

import hashlib
import os
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.utils import json_io

# Snapshot storage location
SNAPSHOTS_DIR = Path(__file__).resolve().parent.parent.parent / "tmp-cache" / "page_snapshots"
SNAPSHOTS_FILE = SNAPSHOTS_DIR / "snapshots.json"

# Default TTL: 7 days
DEFAULT_TTL_DAYS = 7

# Maximum snapshots to keep (cleanup old ones)
MAX_SNAPSHOTS = 500


def _ensure_dir() -> None:
    """Create snapshots directory if it doesn't exist."""
    SNAPSHOTS_DIR.mkdir(parents=True, exist_ok=True)


def _load_snapshots() -> Dict[str, Any]:
    """Load snapshots from storage file."""
    _ensure_dir()
    if not SNAPSHOTS_FILE.exists():
        return {"snapshots": {}}
    try:
        with open(SNAPSHOTS_FILE, "r", encoding="utf-8") as f:
            return json_io.load(f)
    except Exception:
        return {"snapshots": {}}


def _save_snapshots(data: Dict[str, Any]) -> None:
    """Save snapshots to storage file."""
    _ensure_dir()
    with open(SNAPSHOTS_FILE, "w", encoding="utf-8") as f:
        json_io.dump(data, f, indent=2)


def _generate_snapshot_id() -> str:
    """Generate a unique snapshot ID."""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    unique = uuid.uuid4().hex[:8]
    return f"snap_{timestamp}_{unique}"


def _cleanup_expired(snapshots: Dict[str, Any]) -> Dict[str, Any]:
    """Remove expired snapshots."""
    now = datetime.utcnow().isoformat()
    active = {}
    for snap_id, snap_data in snapshots.items():
        expires_at = snap_data.get("expires_at", "")
        if expires_at and expires_at > now:
            active[snap_id] = snap_data
    return active


def _cleanup_overflow(snapshots: Dict[str, Any]) -> Dict[str, Any]:
    """Remove oldest snapshots if exceeding MAX_SNAPSHOTS."""
    if len(snapshots) <= MAX_SNAPSHOTS:
        return snapshots

    # Sort by created_at and keep newest
    sorted_snaps = sorted(
        snapshots.items(),
        key=lambda x: x[1].get("created_at", ""),
        reverse=True
    )
    return dict(sorted_snaps[:MAX_SNAPSHOTS])


def create_snapshot(
    snapshot_type: str,
    data: Any,
    event_id: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> str:
    """
    Create a snapshot of page data and return the snapshot ID.

    Args:
        snapshot_type: Type of snapshot (e.g., "rooms", "products", "offer")
        data: The actual data to store (rooms list, products list, etc.)
        event_id: Optional event ID for context
        params: Original query parameters used to generate this data
        ttl_days: Time-to-live in days (default: 7)

    Returns:
        snapshot_id: Unique identifier for retrieving this snapshot
    """
    storage = _load_snapshots()
    snapshots = storage.get("snapshots", {})

    # Cleanup expired and overflow
    snapshots = _cleanup_expired(snapshots)
    snapshots = _cleanup_overflow(snapshots)

    # Generate new snapshot
    snapshot_id = _generate_snapshot_id()
    now = datetime.utcnow()
    expires = now + timedelta(days=ttl_days)

    snapshot = {
        "snapshot_id": snapshot_id,
        "type": snapshot_type,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "event_id": event_id,
        "params": params or {},
        "data": data,
    }

    snapshots[snapshot_id] = snapshot
    storage["snapshots"] = snapshots
    _save_snapshots(storage)

    return snapshot_id


def get_snapshot(snapshot_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a snapshot by ID.

    Returns None if snapshot doesn't exist or has expired.
    """
    storage = _load_snapshots()
    snapshots = storage.get("snapshots", {})

    snapshot = snapshots.get(snapshot_id)
    if not snapshot:
        return None

    # Check expiration
    expires_at = snapshot.get("expires_at", "")
    if expires_at and expires_at < datetime.utcnow().isoformat():
        return None

    return snapshot


def get_snapshot_data(snapshot_id: str) -> Optional[Any]:
    """
    Retrieve just the data payload from a snapshot.

    Convenience function for when you only need the data.
    """
    snapshot = get_snapshot(snapshot_id)
    if snapshot:
        return snapshot.get("data")
    return None


def list_snapshots(
    snapshot_type: Optional[str] = None,
    event_id: Optional[str] = None,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    List snapshots, optionally filtered by type or event_id.

    Returns metadata only (not full data) for efficiency.
    """
    storage = _load_snapshots()
    snapshots = storage.get("snapshots", {})

    # Cleanup expired first
    snapshots = _cleanup_expired(snapshots)

    results = []
    for snap_id, snap_data in snapshots.items():
        if snapshot_type and snap_data.get("type") != snapshot_type:
            continue
        if event_id and snap_data.get("event_id") != event_id:
            continue

        # Return metadata only
        results.append({
            "snapshot_id": snap_data.get("snapshot_id"),
            "type": snap_data.get("type"),
            "created_at": snap_data.get("created_at"),
            "expires_at": snap_data.get("expires_at"),
            "event_id": snap_data.get("event_id"),
            "params": snap_data.get("params"),
        })

    # Sort by created_at descending
    results.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return results[:limit]


def delete_snapshot(snapshot_id: str) -> bool:
    """Delete a specific snapshot."""
    storage = _load_snapshots()
    snapshots = storage.get("snapshots", {})

    if snapshot_id in snapshots:
        del snapshots[snapshot_id]
        storage["snapshots"] = snapshots
        _save_snapshots(storage)
        return True
    return False


def cleanup_all_expired() -> int:
    """
    Remove all expired snapshots.

    Returns the number of snapshots removed.
    """
    storage = _load_snapshots()
    snapshots = storage.get("snapshots", {})
    original_count = len(snapshots)

    snapshots = _cleanup_expired(snapshots)
    storage["snapshots"] = snapshots
    _save_snapshots(storage)

    return original_count - len(snapshots)


__all__ = [
    "create_snapshot",
    "get_snapshot",
    "get_snapshot_data",
    "list_snapshots",
    "delete_snapshot",
    "cleanup_all_expired",
]
