# Pre-Production Report 03.01.26

## Scope
- Focused on production readiness items excluding ongoing test coverage and test structure consolidation work.
- Reviewed backend API surface, debug tooling, runtime entrypoints, and upload handling.

---

## Completed Tasks

### ✅ Task 5: Production Entrypoint Hygiene (Completed 2026-01-03)

**Problem**: When `backend/main.py` runs directly, it performs several "developer convenience" actions that are dangerous in production:

| Behavior | What it does | Production Risk |
|----------|-------------|-----------------|
| Auto Port Kill | Kills any process on port 8000 | Could kill other services on Hostinger |
| Auto Frontend Launch | Spawns `npm run dev` | Wrong for production (should use pre-built frontend) |
| Auto Browser Open | Opens localhost:3000 in browser | Fails/crashes on headless servers |
| Auto Frontend Fix | Kills frontend + deletes `.next/` if unhealthy | Destroys production cache |

**Root Cause**: These behaviors were controlled by environment variables, but they **defaulted to ENABLED** (`"1"`), meaning production deployments would accidentally trigger them unless explicitly disabled.

**Solution Implemented**: Added `ENV` environment variable to control behavior:

```python
# backend/main.py (line 47-50)
_IS_DEV = os.getenv("ENV", "dev").lower() in ("dev", "development", "local")
```

All 5 auto-behaviors now default based on `ENV`:
- `ENV=dev` (default) → All conveniences enabled (testing works)
- `ENV=prod` → All conveniences disabled (safe for Hostinger)

**Files Modified**:
- `backend/main.py`: Added `_IS_DEV` detection, updated 5 default values, added startup log

**Why This Approach**:
1. **No code divergence**: Same codebase for dev and prod - behavior controlled by environment
2. **Fail-safe production**: Production is safe by default, not dangerous by default
3. **Backward compatible**: Existing explicit env vars (e.g., `AUTO_FREE_BACKEND_PORT=1`) still override
4. **Clear logging**: Startup shows `[Backend] Starting in DEV/PROD mode`

**Testing**:
```bash
# Dev mode (default) - all conveniences enabled
./scripts/dev/dev_server.sh  # Works as before

# Prod mode - all conveniences disabled
ENV=prod uvicorn backend.main:app --host 0.0.0.0 --port 8000
```

---

## Tasks (Remaining - Must Address Before Production)

1) Add authentication/authorization to API routes that mutate config or drive workflows.
   - Target: `backend/api/routes/config.py`, `backend/api/agent_router.py`, `backend/api/routes/messages.py`, `backend/api/routes/tasks.py`, `backend/api/routes/events.py`
   - Rationale: These routes are currently exposed without auth and can be used to mutate state.

2) Gate debug APIs behind an explicit production-off flag and ensure traces are disabled by default in prod.
   - Target: `backend/debug/settings.py`, `backend/api/routes/debug.py`, `backend/main.py`
   - Rationale: Debug endpoints expose internal traces and live logs; `DEBUG_TRACE_DEFAULT` currently enables tracing by default.

3) Gate or remove test-data and universal Q&A endpoints in production.
   - Target: `backend/api/routes/test_data.py`, `backend/main.py`
   - Rationale: These are dev endpoints and expose internal data and stack traces on error.

4) Add request size limits and streaming upload handling for file uploads.
   - Target: `backend/api/agent_router.py`
   - Rationale: Current upload path reads full content into memory with no size limits.

## Proposed Solutions (Backend-Only, Hostinger, Supabase, Multi-Tenancy Pending)
1) Authentication/authorization for state-mutating APIs
   - Add API key/JWT middleware at the FastAPI layer.
   - Enforce auth on config/task/event/agent/message routes.
   - Add per-route role checks (e.g., manager vs. system).

2) Debug endpoints and trace safety
   - Default `DEBUG_TRACE_DEFAULT=0` in production environment.
   - Only mount `debug_router` when `DEBUG_TRACE_ENABLED` is true and `ENV=dev`.
   - Strip stack traces from any API responses in production mode.

3) Dev/test endpoints gating
   - Do not mount `test_data_router` in production.
   - For `/api/qna`, return sanitized error payloads (no tracebacks).
   - Add `ENV=dev` guard or `ALLOW_TEST_ENDPOINTS=1` flag.

4) Upload safety and limits
   - Add request size limits (FastAPI + reverse proxy).
   - Stream uploads to disk or object storage (avoid full in-memory reads).
   - Validate content type and enforce allowlists.

5) Production entrypoint hygiene
   - Do not use `python backend/main.py` in production; use `uvicorn`/ASGI.
   - Gate `_ensure_backend_port_free` and auto browser launch behind `DEV_MODE=1`.

6) Supabase integration readiness
   - Enable `OE_INTEGRATION_MODE=supabase` and validate required env vars.
   - Ensure all write paths use Supabase adapters (events, tasks, emails).
   - Add migration step to backfill JSON data into Supabase before cutover.

7) Multi-tenancy groundwork (must land before production if required)
   - Enforce `team_id` and `system_user_id` in all data writes.
   - Add tenant scoping to every query (team_id filter).
   - Add per-tenant API keys or JWT claims with team_id.

## Notes on Deployment Context
- Backend hosted on Hostinger; frontend is separate. Focus is API hardening, auth, and environment gating.
- Supabase will replace JSON storage; ensure integration flags and adapters are treated as source-of-truth.
- Multi-tenancy is still open; treat as a pre-production blocker if required for launch.

## Tasks (Should Address Soon After Production)
6) Add rate limiting for public-facing endpoints.
   - Target: API layer (FastAPI middleware or gateway)
   - Rationale: Mitigates abuse and accidental overload.

7) Add structured error handling that avoids returning stack traces to clients.
   - Target: `backend/api/routes/test_data.py` and any endpoints returning raw exceptions.

## Notes
- This report excludes the in-progress priorities:
  - Priority 3: Add Steps 5-7 test coverage
  - Priority 4: Consolidate test structure
