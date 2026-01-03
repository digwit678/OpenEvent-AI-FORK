# Multi-Tenancy Implementation Plan + File Map (03.01.26)

## Completed Phases

### ✅ Phase 1: Tenant Context Infrastructure (Completed 2026-01-03)

Added request-scoped tenant context middleware as foundation for multi-tenancy.

**What Was Implemented**:
- Created `backend/api/middleware/tenant_context.py` with:
  - `TenantContextMiddleware` - extracts `X-Team-Id` and `X-Manager-Id` headers
  - `CURRENT_TEAM_ID` / `CURRENT_MANAGER_ID` contextvars for request-scoped storage
  - `get_request_team_id()` / `get_request_manager_id()` helper functions
- Registered middleware in `backend/main.py`
- Added tests in `backend/tests/api/test_tenant_context.py`

**Behavior**:
- Middleware only active when `TENANT_HEADER_ENABLED=1` (default: `"0"`)
- No behavior change to existing code - this is pure infrastructure
- Headers are parsed and stored in contextvars

---

### ✅ Phase 2A: Connect Contextvar to Config (Completed 2026-01-03)

Connected the request-scoped contextvars to the config layer.

**What Was Implemented**:
- Updated `get_team_id()` in `backend/workflows/io/integration/config.py`:
  - Checks contextvar first (set by middleware)
  - Falls back to env var `OE_TEAM_ID` if not set
- Updated `get_system_user_id()` with same pattern:
  - Checks contextvar first
  - Falls back to env var `OE_SYSTEM_USER_ID`
- Added 5 integration tests in `backend/tests/api/test_tenant_context.py`

**Behavior**:
- **Zero change for existing code** - contextvar defaults to `None`, so falls back to env var
- When `TENANT_HEADER_ENABLED=1` and headers are set: contextvar takes priority
- All 9 Supabase adapter functions using `get_team_id()` automatically respect the contextvar

---

### ✅ Phase 2B: JSON DB Per-Team File Routing (Completed 2026-01-03)

Route JSON database reads/writes to per-team files when team_id is set.

**What Was Implemented**:
- Added `_resolve_db_path()` helper in `JSONDatabaseAdapter`
- Updated `_load()` and `_save()` to use dynamic path resolution
- Added `_resolve_tenant_db_path()` in `workflow_email.py` for workflow-level routing
- Updated `process_msg()`, `load_db()`, `save_db()` to use tenant-aware paths
- Pattern: `events_{team_id}.json` when team_id set, else `events_database.json`

**Behavior**:
- Singleton adapter preserved - path resolved per-call
- Backwards compatible: No team_id → uses default path
- Each team gets isolated JSON file
- **Verified**: API requests with `X-Team-Id` header create separate database files
- **Tested**: Team A cannot see Team B's clients (full isolation)

**Files Modified**:
- `backend/workflows/io/integration/adapter.py`
- `backend/workflow_email.py` (added tenant path resolution)
- `backend/tests/api/test_tenant_context.py` (+4 routing tests)
- `scripts/dev/dev_server.sh` (enabled TENANT_HEADER_ENABLED by default for dev)

**To Enable in Dev**:
```bash
# Automatic in dev (scripts/dev/dev_server.sh sets TENANT_HEADER_ENABLED=1)
# Send headers with API requests:
curl -H "X-Team-Id: my-team" -H "X-Manager-Id: manager-1" ...
```

---

### ✅ Phase 2C: Frontend Manager Selector (Completed 2026-01-03)

Added manager selector dropdown to frontend for switching between event managers in test environment.

**What Was Implemented**:
- Added `Manager` interface and `AVAILABLE_MANAGERS` list with 3 test managers (Shami, Alex, Jordan)
- Created `setTenantHeaders()` function to set global tenant headers
- Modified `requestJSON()` to include `X-Team-Id` and `X-Manager-Id` headers
- Modified `fetchWorkflowReply()` to include tenant headers
- Added `handleManagerSwitch()` callback that:
  - Updates tenant headers
  - Resets all conversation state (session, messages, tasks, debugger)
  - Refreshes tasks for the new manager's team
- Added dropdown UI in header with team ID display

**Files Modified**:
- `atelier-ai-frontend/app/page.tsx`

**UI Features**:
- Manager name displayed in header with dropdown icon
- Dropdown shows all available managers with current selection highlighted
- Team ID shown in dropdown footer
- Switching managers resets entire conversation state

**E2E Test Results** (Verified 2026-01-03):
- ✅ Manager selector UI works correctly
- ✅ State reset on manager switch works
- ✅ Per-team JSON files created (`events_team-shami.json`, `events_team-alex.json`)
- ✅ Full client isolation - Shami's clients not visible to Alex
- ✅ Workflow progresses correctly with tenant context
- Screenshot saved: `.playwright-mcp/multi-tenancy-e2e-test.png`

---

### ✅ Phase 3: Supabase RLS + Record-Level team_id (Completed 2026-01-03)

Added production-ready security: RLS policies + explicit team_id in all records.

**Part A - JSON DB team_id in Records**:
- Added `team_id` field to `create_event_entry()` in `database.py`
- Added `team_id` to `ensure_event_defaults()` for backwards compatibility
- Each event record now explicitly stores its owning team

**Part B - Supabase Adapter Fixes**:
Fixed 4 missing team_id filters:
- `upsert_client()` UPDATE - now includes `.eq("team_id", team_id)`
- `update_event_metadata()` - now filters by team_id on update
- `get_room_by_id()` - now filters rooms by team_id
- `create_offer()` - now includes team_id in offers and offer_line_items

**Part C - RLS SQL Migration**:
- Created `supabase/migrations/20260103000000_enable_rls_team_isolation.sql`
- Enables RLS on 8 tables: clients, events, tasks, emails, rooms, products, offers, offer_line_items
- Creates team isolation policies using `current_setting('app.team_id')`
- Creates service_role bypass policies for backend operations
- Adds team_id indexes for query performance

**Files Modified**:
- `backend/workflows/io/database.py` - Added team_id to event creation
- `backend/workflows/io/integration/supabase_adapter.py` - Fixed 4 team_id gaps
- `supabase/migrations/20260103000000_enable_rls_team_isolation.sql` - NEW: RLS policies

**Deployment Notes**:
- RLS migration should be run during maintenance window
- Backend uses service_role, so no code changes needed for RLS
- For non-service-role connections: `SET LOCAL app.team_id = 'uuid'`

---

## Goal
Enable switching the current event manager in the backend and ensure each manager only accesses their own clients/events/tasks. Data must be isolated by tenant (team/manager) in both test (JSON DB) and production (Supabase).

## Target Model
- Tenant boundary: `team_id` (venue/team) + `manager_user_id` (actor identity).
- Every client, event, task, email, and config row is scoped to `team_id`.
- Backend must always apply `team_id` filters when reading or writing data.

## Phase 0: JSON DB First (Test Environment, Non-Breaking)
1) Keep current single-tenant behavior as default.
2) Allow per-request tenant override via headers for local/testing:
   - `X-Team-Id` (required to switch tenant)
   - `X-Manager-Id` (optional actor identity)
3) If headers are absent, fall back to existing env vars:
   - `OE_TEAM_ID`, `OE_SYSTEM_USER_ID`, `OE_EMAIL_ACCOUNT_ID`
4) All tenant resolution should be in a single place (middleware + contextvar).
5) JSON mode routes reads/writes to per-team JSON files, e.g. `events_<team_id>.json`.
   - Default remains the current JSON file when no team_id is provided.

## Phase 0.5: Supabase Section (Later, Integration Phase)
- Supabase becomes the source of truth when `OE_INTEGRATION_MODE=supabase`.
- The same request-scoped tenant context is used for filtering and writes.
- RLS + JWT claims enforce isolation in production.

## Production Strategy (Supabase)
- Tenant context is derived from authenticated identity (Supabase auth/JWT claims).
- Enforce tenant isolation with RLS policies on all tenant-scoped tables.
- Backend uses service role only when absolutely required; otherwise rely on RLS.

## Implementation Plan

### Phase 1: Tenant Context (No Behavior Change)
1) Add tenant context resolver in API layer:
   - Middleware reads `X-Team-Id`/`X-Manager-Id` (test env only) and stores in `request.state` + contextvar.
2) Update tenant helpers to read from contextvar first, then env default:
   - `get_team_id()`
   - `get_system_user_id()`
   - `get_email_account_id()` (if needed)
3) Keep JSON mode unchanged unless `X-Team-Id` is provided; then use per-team JSON file.

### Phase 2: JSON DB Isolation
1) Route JSON reads/writes to `events_<team_id>.json` when `team_id` is present.
2) Ensure every JSON load/save uses the resolved per-request team_id.
3) Add a small migration helper to copy baseline data into a new team file when switching.

### Phase 3: Supabase Data Access Enforcement
1) Ensure every Supabase query uses the resolved `team_id`:
   - Clients, events, tasks, emails, snapshots, config.
2) Update any helper functions that bypass the adapter and access Supabase directly.
3) Update venue/config accessors to be team-scoped (config table or config rows keyed by team).

### Phase 4: RLS + Schema (Supabase)
1) Add `team_id` to relevant tables if missing (clients, events, hil_tasks, emails, configs, snapshots).
2) Create RLS policies:
   - `team_id = auth.jwt()->>"team_id"`
3) Add indexes for `team_id` and `team_id + primary key` pairs.

### Phase 5: Switch-User Capability
1) In test env, switching manager is simply changing headers.
2) In production, switching manager is selecting a different user/team via auth (frontend handled).
3) Add an admin-only endpoint to validate a `team_id` header in test env (optional).

### Phase 6: Safety + Verification
1) Add audit logging of `team_id` and actor id on writes.
2) Add integration checks that attempt cross-tenant reads and ensure they fail.
3) Confirm that a manager sees only their clients/events/tasks.

## File Map (Multi-Tenancy Related)

### Tenant Config + Helpers
- `backend/workflows/io/integration/config.py`
  - Reads `OE_TEAM_ID`, `OE_SYSTEM_USER_ID`, `OE_EMAIL_ACCOUNT_ID`.
  - Needs request-scoped override (contextvar).

### JSON Database Layer
- `backend/workflows/io/integration/adapter.py`
  - JSON adapter entrypoint; ideal place to inject per-team JSON db path.
- `backend/workflows/io/database.py`
  - JSON DB load/save logic (lock path support).
- `backend/workflow_email.py`
  - Uses JSON DB path; ensure tenant-aware path routing in JSON mode.

### Supabase Adapters
- `backend/workflows/io/integration/supabase_adapter.py`
  - All Supabase CRUD calls; currently uses `get_team_id()`.
  - Update to honor request-scoped team_id.
- `backend/workflows/io/integration/uuid_adapter.py`
  - Client lookup by email supports `team_id` parameter.
  - Ensure caller passes per-request team_id.
- `backend/workflows/io/integration/hil_tasks.py`
  - Task creation uses team_id; must remain scoped.
- `backend/workflows/io/integration/field_mapping.py`
  - Field mapping for Supabase records; ensure team_id mapping and query filters align.
- `backend/workflows/io/integration/test_connection.py`
  - Smoke tests already filter by `team_id`.

### Venue / Config (Multi-Tenant Branding)
- `backend/api/routes/config.py`
  - Venue configuration endpoints mention multi-tenant usage.
  - Must be scoped by team_id once multi-tenancy is enabled.
- `backend/workflows/io/config_store.py`
  - Venue config currently global; needs per-team storage in Supabase.

### Data Models / Schemas
- `backend/workflows/io/site_visit_models.py`
  - Includes `team_id` in site visit models.

### API Routing (Tenant Access Control)
- `backend/api/routes/events.py`
- `backend/api/routes/clients.py`
- `backend/api/routes/tasks.py`
- `backend/api/routes/messages.py`
- `backend/api/routes/emails.py`
  - Add tenant context usage and filters to every list/lookup.

## Notes
- This plan does not change the frontend; backend can accept headers in test env.
- The safest path is: contextvar + per-request tenant, then enforce RLS.
- JSON mode multi-tenancy is a per-team DB file mapping, activated only when team headers are present.

## Middleware Skeleton (Test Env Header Switching)
```python
from contextvars import ContextVar
from fastapi import Request

CURRENT_TEAM_ID: ContextVar[str | None] = ContextVar("CURRENT_TEAM_ID", default=None)
CURRENT_MANAGER_ID: ContextVar[str | None] = ContextVar("CURRENT_MANAGER_ID", default=None)

def get_request_team_id() -> str | None:
    return CURRENT_TEAM_ID.get()

def get_request_manager_id() -> str | None:
    return CURRENT_MANAGER_ID.get()

async def tenant_context_middleware(request: Request, call_next):
    # Only allow header overrides in test/dev environments.
    if os.getenv("TENANT_HEADER_ENABLED", "0") == "1":
        team_id = request.headers.get("X-Team-Id")
        manager_id = request.headers.get("X-Manager-Id")
        if team_id:
            CURRENT_TEAM_ID.set(team_id)
        if manager_id:
            CURRENT_MANAGER_ID.set(manager_id)
    return await call_next(request)
```

## JSON DB Path Resolver (Adapter Hook)
```python
def resolve_json_db_path(default_path: Path) -> Path:
    team_id = get_request_team_id() or os.getenv("OE_TEAM_ID")
    if not team_id:
        return default_path
    return default_path.with_name(f"events_{team_id}.json")
```

## Recommended Env Defaults
```text
TENANT_HEADER_ENABLED=0        # Enable in test only
OE_TEAM_ID=                    # Optional fallback for single-tenant runs
OE_SYSTEM_USER_ID=             # Optional actor id fallback
OE_EMAIL_ACCOUNT_ID=           # Optional, if email storage requires it
OE_INTEGRATION_MODE=json       # Default in test env; switch to supabase later
```
