"""
Supabase adapter for snapshot storage.

When OE_INTEGRATION_MODE=supabase, snapshots are stored in the Supabase
`snapshots` table instead of local JSON files. This enables:
1. Multi-worker deployments (all workers share the same snapshots)
2. Proper concurrency handling (database transactions)
3. Cross-instance access for info page links

Required Supabase table:
```sql
CREATE TABLE snapshots (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id UUID NOT NULL REFERENCES teams(id),
    snapshot_type TEXT NOT NULL,  -- "rooms", "products", "offer", etc.
    event_id UUID REFERENCES events(id),
    params JSONB DEFAULT '{}',
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL
);

-- Index for efficient lookups
CREATE INDEX idx_snapshots_team_type ON snapshots(team_id, snapshot_type);
CREATE INDEX idx_snapshots_expires ON snapshots(expires_at);

-- RLS policy for multi-tenancy
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY snapshots_team_isolation ON snapshots
    FOR ALL USING (team_id = current_setting('app.current_team_id')::uuid);
```

Usage:
    This module is called by page_snapshots.py when integration mode is enabled.
    It provides the same interface as the local JSON storage functions.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from .config import get_team_id

logger = logging.getLogger(__name__)

# Default TTL: 7 days (same as local storage)
DEFAULT_TTL_DAYS = 7

# Maximum snapshots per team (cleanup old ones)
MAX_SNAPSHOTS_PER_TEAM = 500


def _get_client():
    """Get Supabase client (lazy import to avoid circular deps)."""
    from .supabase_adapter import get_supabase_client
    return get_supabase_client()


def _generate_snapshot_id() -> str:
    """Generate a unique snapshot ID (UUID format for Supabase)."""
    return str(uuid.uuid4())


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
        snapshot_id: UUID identifier for retrieving this snapshot
    """
    client = _get_client()
    team_id = get_team_id()

    if not team_id:
        logger.warning("No team_id available for snapshot creation")
        raise ValueError("team_id required for Supabase snapshots")

    now = datetime.utcnow()
    expires = now + timedelta(days=ttl_days)

    snapshot_id = _generate_snapshot_id()

    record = {
        "id": snapshot_id,
        "team_id": team_id,
        "snapshot_type": snapshot_type,
        "event_id": event_id,
        "params": params or {},
        "data": data,
        "created_at": now.isoformat(),
        "expires_at": expires.isoformat(),
    }

    try:
        client.table("snapshots").insert(record).execute()
        logger.debug("Created snapshot %s (type=%s)", snapshot_id, snapshot_type)

        # Cleanup old snapshots asynchronously (best effort)
        _cleanup_old_snapshots(client, team_id)

        return snapshot_id

    except Exception as e:
        logger.error("Failed to create snapshot: %s", e)
        raise


def get_snapshot(snapshot_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieve a snapshot by ID.

    Returns None if snapshot doesn't exist or has expired.
    """
    client = _get_client()
    team_id = get_team_id()

    if not team_id:
        return None

    try:
        result = client.table("snapshots") \
            .select("*") \
            .eq("id", snapshot_id) \
            .eq("team_id", team_id) \
            .gt("expires_at", datetime.utcnow().isoformat()) \
            .maybe_single() \
            .execute()

        if result.data:
            # Convert to expected format
            return {
                "snapshot_id": result.data["id"],
                "type": result.data["snapshot_type"],
                "created_at": result.data["created_at"],
                "expires_at": result.data["expires_at"],
                "event_id": result.data.get("event_id"),
                "params": result.data.get("params", {}),
                "data": result.data.get("data"),
            }
        return None

    except Exception as e:
        logger.error("Failed to get snapshot %s: %s", snapshot_id, e)
        return None


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
    client = _get_client()
    team_id = get_team_id()

    if not team_id:
        return []

    try:
        query = client.table("snapshots") \
            .select("id, snapshot_type, created_at, expires_at, event_id, params") \
            .eq("team_id", team_id) \
            .gt("expires_at", datetime.utcnow().isoformat())

        if snapshot_type:
            query = query.eq("snapshot_type", snapshot_type)
        if event_id:
            query = query.eq("event_id", event_id)

        result = query \
            .order("created_at", desc=True) \
            .limit(limit) \
            .execute()

        return [
            {
                "snapshot_id": row["id"],
                "type": row["snapshot_type"],
                "created_at": row["created_at"],
                "expires_at": row["expires_at"],
                "event_id": row.get("event_id"),
                "params": row.get("params", {}),
            }
            for row in (result.data or [])
        ]

    except Exception as e:
        logger.error("Failed to list snapshots: %s", e)
        return []


def delete_snapshot(snapshot_id: str) -> bool:
    """Delete a specific snapshot."""
    client = _get_client()
    team_id = get_team_id()

    if not team_id:
        return False

    try:
        result = client.table("snapshots") \
            .delete() \
            .eq("id", snapshot_id) \
            .eq("team_id", team_id) \
            .execute()

        return len(result.data or []) > 0

    except Exception as e:
        logger.error("Failed to delete snapshot %s: %s", snapshot_id, e)
        return False


def cleanup_all_expired() -> int:
    """
    Remove all expired snapshots for the current team.

    Returns the number of snapshots removed.
    """
    client = _get_client()
    team_id = get_team_id()

    if not team_id:
        return 0

    try:
        result = client.table("snapshots") \
            .delete() \
            .eq("team_id", team_id) \
            .lt("expires_at", datetime.utcnow().isoformat()) \
            .execute()

        count = len(result.data or [])
        if count > 0:
            logger.info("Cleaned up %d expired snapshots", count)
        return count

    except Exception as e:
        logger.error("Failed to cleanup expired snapshots: %s", e)
        return 0


def delete_snapshots_for_event(event_id: str) -> int:
    """
    Delete all snapshots associated with an event.

    Call this when a booking is completed/cancelled to clean up
    associated info page data (rooms, offers, etc.).

    Args:
        event_id: The event ID whose snapshots should be deleted

    Returns:
        Number of snapshots deleted
    """
    client = _get_client()
    team_id = get_team_id()

    if not team_id:
        return 0

    try:
        result = client.table("snapshots") \
            .delete() \
            .eq("team_id", team_id) \
            .eq("event_id", event_id) \
            .execute()

        count = len(result.data or [])
        if count > 0:
            logger.info("Deleted %d snapshots for event %s", count, event_id)
        return count

    except Exception as e:
        logger.error("Failed to delete snapshots for event %s: %s", event_id, e)
        return 0


def _cleanup_old_snapshots(client, team_id: str) -> None:
    """
    Remove oldest snapshots if team exceeds MAX_SNAPSHOTS_PER_TEAM.

    Called after creating a new snapshot (best effort, non-blocking).
    """
    try:
        # Count current snapshots
        count_result = client.table("snapshots") \
            .select("id", count="exact") \
            .eq("team_id", team_id) \
            .execute()

        total = count_result.count or 0
        if total <= MAX_SNAPSHOTS_PER_TEAM:
            return

        # Find oldest to delete
        excess = total - MAX_SNAPSHOTS_PER_TEAM
        oldest = client.table("snapshots") \
            .select("id") \
            .eq("team_id", team_id) \
            .order("created_at", desc=False) \
            .limit(excess) \
            .execute()

        if oldest.data:
            ids_to_delete = [row["id"] for row in oldest.data]
            client.table("snapshots") \
                .delete() \
                .in_("id", ids_to_delete) \
                .execute()
            logger.info("Cleaned up %d overflow snapshots", len(ids_to_delete))

    except Exception as e:
        # Best effort - don't fail the main operation
        logger.warning("Failed to cleanup overflow snapshots: %s", e)


__all__ = [
    "create_snapshot",
    "get_snapshot",
    "get_snapshot_data",
    "list_snapshots",
    "delete_snapshot",
    "delete_snapshots_for_event",
    "cleanup_all_expired",
]
