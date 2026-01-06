# Production Readiness Gaps - 2026-01-05

## Scope

- Backend production readiness (frontend excluded)
- Assumes known toggles are handled (AUTH_ENABLED/ENV set in prod, rate limiting module exists, LLM sanitization wired)

## Remaining Gaps (Non-toggle)

### Snapshot Storage Multi-Worker Support

**Status**: Solution implemented, pending Supabase table creation

**Problem**: Snapshot storage is local JSON with no file locking; multi-worker deployments can corrupt snapshots or lose cross-instance access.

**Solution**: Supabase adapter created. When `OE_INTEGRATION_MODE=supabase`, snapshots are stored in database instead of local JSON.

**Files Created**:
- `backend/workflows/io/integration/supabase_snapshots.py` - Supabase adapter
- `backend/utils/page_snapshots.py` - Updated with routing logic

**To Enable**:
1. Create Supabase table (SQL below)
2. Set `OE_INTEGRATION_MODE=supabase` (already done if using Supabase for events)

**Required Supabase Migration**:
```sql
-- Snapshots table for info page data
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

-- Indexes for efficient lookups
CREATE INDEX idx_snapshots_team_type ON snapshots(team_id, snapshot_type);
CREATE INDEX idx_snapshots_event ON snapshots(event_id);
CREATE INDEX idx_snapshots_expires ON snapshots(expires_at);

-- RLS policy for multi-tenancy
ALTER TABLE snapshots ENABLE ROW LEVEL SECURITY;

CREATE POLICY snapshots_team_isolation ON snapshots
    FOR ALL USING (team_id = current_setting('app.current_team_id')::uuid);
```

**Cleanup Strategy**:
- Max count: 500 per team (oldest evicted on overflow)
- Event cleanup: `delete_snapshots_for_event(event_id)` - call when event status → confirmed/cancelled
- TTL by type:
  - `offer`, `rooms` (event-specific): 7 days default, OR until event completes
  - `qna` (general info): 365 days - clients may reference after event

**TODO**: Hook `delete_snapshots_for_event()` into Step 7 confirmation flow when event reaches terminal status (confirmed, cancelled). Q&A snapshots without event_id should use longer TTL.

---

## Fixed Gaps (2026-01-05)

- **FIXED**: JSON DB lockfile can be left behind on crash, blocking all writes until manual cleanup.
  - Fix: Added `_cleanup_stale_lock()` that detects dead owner PIDs and removes orphaned lockfiles on startup.
  - Reference: `backend/workflows/io/database.py:20-55`

- **FIXED**: LLM analysis cache is unbounded and retains message content indefinitely, risking memory growth and PII retention.
  - Fix: Converted to bounded LRU cache (OrderedDict) with configurable max size (default 500 entries via `LLM_CACHE_MAX_SIZE` env var). Oldest entries evicted when limit exceeded.
  - Reference: `backend/workflows/llm/adapter.py:39-43, 359-384`

- **FIXED**: No API-layer request size limits (DoS risk) for message endpoints.
  - Fix: Added `RequestSizeLimitMiddleware` that rejects requests exceeding configurable limit (default 1MB via `REQUEST_SIZE_LIMIT_KB` env var).
  - Reference: `backend/api/middleware/request_limits.py`, `backend/main.py`

- **FIXED**: Allowlisted health/root endpoints expose event counts and DB path even when auth is enabled.
  - Fix: Health endpoints now only expose detailed info in dev mode (`ENV != prod`). Production returns minimal `{"ok": true}` or `{"status": "ok"}`.
  - Reference: `backend/main.py:434-449`, `backend/api/routes/workflow.py:20-34`
