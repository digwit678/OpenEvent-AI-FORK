# Authentication Implementation Plan (03.01.26)

## Goal
Add backend authentication and authorization without breaking current behavior. Default remains unauthenticated in test/dev; production enables auth via toggle.

## Constraints
- Do not break existing dev/test workflows.
- Backend must remain compatible with JSON DB first, then Supabase.
- Frontend is a separate codebase; backend must support a clean toggle for prod.

## Approach Overview
- Add a single auth middleware with a production toggle:
  - `AUTH_ENABLED=0` (default) -> no auth checks.
  - `AUTH_ENABLED=1` -> require auth on protected endpoints.
- Support two modes:
  - `AUTH_MODE=api_key` (simple API key for initial prod rollout)
  - `AUTH_MODE=supabase_jwt` (later, use Supabase auth + claims)

## Implementation Status

| Phase | Status | Date |
|-------|--------|------|
| Phase 1: Toggle + Middleware | ✅ Complete | 2026-01-03 |
| Phase 2: API Key Mode | ✅ Complete | 2026-01-03 |
| Phase 3: Supabase JWT Mode | ⏳ Pending | - |
| Phase 4: Authorization (Roles) | ⏳ Pending | - |

## Implementation Plan

### ✅ Phase 1: Toggle + Middleware (Completed 2026-01-03)
1) Add auth middleware to the FastAPI app:
   - If `AUTH_ENABLED=0`, return immediately (no changes to behavior).
   - If enabled, enforce auth on protected routes.
2) Add an allowlist for public routes (health, static, optional test endpoints in dev only).
3) Add structured error responses (401/403) without stack traces.

### ✅ Phase 2: API Key Mode (Completed 2026-01-03)
1) Read `API_KEY` from env.
2) Require `Authorization: Bearer <API_KEY>` for all protected routes.
3) Optionally add `X-Api-Key` fallback for internal tools.
4) Log auth failures with redacted tokens.

**Files Created:**
- `backend/api/middleware/auth.py` - Auth middleware implementation
- `backend/tests/api/test_auth_middleware.py` - 24 tests (all passing)

### Phase 3: Supabase JWT Mode (Production, Full Auth)
1) Validate Supabase JWT signature using `SUPABASE_JWT_SECRET` or JWKS.
2) Extract claims:
   - `sub` -> manager/user id
   - `team_id` -> tenant scoping
3) Set request context (manager id + team id) for multi-tenancy.

### Phase 4: Authorization (Role + Scope)
1) Add role checks (e.g., `manager`, `admin`, `system`).
2) Restrict config mutations and admin operations to privileged roles.

## How This Avoids Breaking Current Code
- Default stays `AUTH_ENABLED=0`.
- No route signatures change.
- Middleware only activates in production when env toggle is set.
- Local testing can remain unchanged.

## Integration Points
- `backend/main.py` (middleware registration)
- `backend/api/routes/*` (route grouping and allowlist)
- `backend/workflows/io/integration/config.py` (future: derive team_id from auth claims)

## Environment Variables
- `AUTH_ENABLED` (0/1)
- `AUTH_MODE` (`api_key` | `supabase_jwt`)
- `API_KEY` (for api_key mode)
- `SUPABASE_JWT_SECRET` or `SUPABASE_JWKS_URL` (for supabase_jwt mode)

## Middleware Skeleton (Toggle-Friendly)
```python
from fastapi import Request
from starlette.responses import JSONResponse

ALLOWLIST_PREFIXES = ("/health", "/docs", "/openapi.json")

async def auth_middleware(request: Request, call_next):
    if os.getenv("AUTH_ENABLED", "0") != "1":
        return await call_next(request)

    path = request.url.path
    if path.startswith(ALLOWLIST_PREFIXES):
        return await call_next(request)

    mode = os.getenv("AUTH_MODE", "api_key")
    auth_header = request.headers.get("Authorization", "")

    if mode == "api_key":
        expected = os.getenv("API_KEY")
        token = auth_header.removeprefix("Bearer ").strip()
        if not expected or token != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)

    if mode == "supabase_jwt":
        # Validate JWT and extract claims here (sub, team_id, role).
        # Populate request.state / contextvars for downstream access.
        return await call_next(request)

    return JSONResponse({"error": "auth_mode_invalid"}, status_code=500)
```

## Recommended Env Defaults
```text
AUTH_ENABLED=0
AUTH_MODE=api_key
API_KEY=
SUPABASE_JWT_SECRET=
SUPABASE_JWKS_URL=
```

## Notes for Other Devs
- Always implement auth checks in one place (middleware).
- Keep dev/test defaults off to avoid friction.
- When switching to Supabase auth, also enable multi-tenant context from JWT claims.
