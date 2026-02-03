# Backend TODO for OpeneventGithub Frontend Integration

This document tracks backend work needed to fully support the OpeneventGithub production frontend.

## Current Status

| Feature | Backend Status | Frontend Ready |
|---------|----------------|----------------|
| Prompts Editor API | ✅ Done | Docs ready |
| CORS Configuration | ✅ Done | - |
| Auth Headers | ✅ Done | Ready |
| Team Context | ✅ Done | Ready |
| JWT Verification | ✅ Done | Ready |
| Admin Role Guard | ✅ Done | Ready |
| Supabase Storage | 🔲 TODO | Required |

> **Supabase Schema:** See `docs/integration/SUPABASE_INTEGRATION.md` for schema requirements.

### Recent Completions (Feb 2026)

**P1: Team Context** - Team-scoped config via `X-Team-Id` header or JWT claims
**P3: JWT Verification** - Full Supabase JWT decode with signature verification
**P4: Admin Role Guard** - `require_admin_role()` protects all POST config endpoints

---

## Priority 1: Team Context Support (Required)

The OpeneventGithub frontend is **multi-tenant** - every request includes a `team_id` to scope data.

### Current Backend Behavior
- Uses `X-Team-Id` header for tenant isolation
- Stores data in JSON file per tenant

### Required Changes

#### 1. Accept Team ID from Frontend Auth Token

OpeneventGithub sends Supabase auth tokens. The backend should:

```python
# In api/routes/config.py or a middleware

from fastapi import Header, Depends
import jwt

async def get_team_context(
    authorization: str = Header(None),
    x_team_id: str = Header(None, alias="X-Team-Id")
) -> str:
    """
    Extract team_id from either:
    1. X-Team-Id header (current method, for testing)
    2. Supabase JWT token (production method)
    """
    if x_team_id:
        return x_team_id

    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        # Decode Supabase JWT (no verification needed for team_id extraction)
        payload = jwt.decode(token, options={"verify_signature": False})
        # OpeneventGithub stores selected team in user metadata or passes separately
        return payload.get("team_id") or x_team_id

    return "default"  # Fallback for testing
```

#### 2. Update All Config Endpoints

Each `/api/config/*` endpoint should scope by team:

```python
@router.get("/api/config/prompts")
async def get_prompts(team_id: str = Depends(get_team_context)):
    # Load prompts for this team only
    return load_config(f"prompts.{team_id}")
```

**Files to update:**
- `api/routes/config.py` - All config endpoints
- `api/routes/events.py` - Events list/detail
- `api/routes/tasks.py` - HIL tasks

---

## Priority 2: Supabase Integration (Required for Production)

OpeneventGithub uses Supabase for all data. For full integration:

### Option A: Keep JSON + Sync (Simpler)
Keep current JSON storage, sync to Supabase periodically.

```python
# After saving to JSON, also sync to Supabase
async def sync_to_supabase(team_id: str, config_key: str, data: dict):
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    await supabase.table("ai_config").upsert({
        "team_id": team_id,
        "config_key": config_key,
        "data": data,
        "updated_at": datetime.now().isoformat()
    }).execute()
```

### Option B: Full Supabase Storage (Recommended)
Replace JSON storage with Supabase queries.

**Required Supabase table:**
```sql
CREATE TABLE ai_config (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    team_id UUID REFERENCES teams(id),
    config_key TEXT NOT NULL,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(team_id, config_key)
);

-- Enable RLS
ALTER TABLE ai_config ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only access their team's config
CREATE POLICY "Team members can access their config"
ON ai_config FOR ALL
USING (team_id IN (
    SELECT team_id FROM team_members_new
    WHERE user_id = auth.uid() AND invitation_status = 'active'
));
```

**Backend changes:**
```python
# New: api/storage/supabase_storage.py
from supabase import create_client

class SupabaseConfigStorage:
    def __init__(self):
        self.client = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_SERVICE_KEY")  # Service key for backend
        )

    async def get(self, team_id: str, key: str) -> dict:
        result = await self.client.table("ai_config")\
            .select("data")\
            .eq("team_id", team_id)\
            .eq("config_key", key)\
            .single()\
            .execute()
        return result.data["data"] if result.data else {}

    async def set(self, team_id: str, key: str, data: dict):
        await self.client.table("ai_config").upsert({
            "team_id": team_id,
            "config_key": key,
            "data": data,
            "updated_at": datetime.now().isoformat()
        }).execute()
```

**Environment variables needed:**
```bash
SUPABASE_URL=https://igrfkpxebvuvfwogondx.supabase.co
SUPABASE_SERVICE_KEY=eyJ...  # Service role key (NOT the anon key)
```

---

## Priority 3: Authentication Middleware (Security)

For production, verify Supabase JWT tokens.

### Add JWT Verification Middleware

```python
# api/middleware/auth.py
from fastapi import Request, HTTPException
from supabase import create_client
import os

async def verify_supabase_token(request: Request):
    """Verify the Supabase JWT token for protected routes."""
    if os.getenv("AUTH_ENABLED") != "1":
        return  # Skip in development

    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing auth token")

    token = auth_header.split(" ")[1]

    # Verify with Supabase
    supabase = create_client(
        os.getenv("SUPABASE_URL"),
        os.getenv("SUPABASE_ANON_KEY")
    )

    try:
        user = supabase.auth.get_user(token)
        request.state.user = user
        request.state.user_id = user.user.id
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")
```

### Apply to Routes

```python
# In api/routes/config.py
from api.middleware.auth import verify_supabase_token

@router.get("/api/config/prompts")
async def get_prompts(
    request: Request,
    _: None = Depends(verify_supabase_token),
    team_id: str = Depends(get_team_context)
):
    # Request now has request.state.user_id
    ...
```

---

## Priority 4: Admin Role Verification

OpeneventGithub checks roles client-side, but backend should also verify.

### Role Check Helper

```python
async def require_admin_role(
    request: Request,
    team_id: str = Depends(get_team_context)
) -> bool:
    """Verify user has admin or owner role for this team."""
    user_id = request.state.user_id

    supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

    # Check team_members_new table
    result = await supabase.table("team_members_new")\
        .select("role")\
        .eq("team_id", team_id)\
        .eq("user_id", user_id)\
        .eq("invitation_status", "active")\
        .single()\
        .execute()

    if not result.data:
        # Check if user is team owner
        team = await supabase.table("teams")\
            .select("owner_id")\
            .eq("id", team_id)\
            .single()\
            .execute()

        if team.data and team.data["owner_id"] == user_id:
            return True

        raise HTTPException(status_code=403, detail="Admin role required")

    role = result.data["role"]
    if role not in ["admin", "owner"]:
        raise HTTPException(status_code=403, detail="Admin role required")

    return True
```

### Apply to Admin-Only Endpoints

```python
@router.post("/api/config/prompts")
async def save_prompts(
    config: PromptConfig,
    _: bool = Depends(require_admin_role),  # Must be admin
    team_id: str = Depends(get_team_context)
):
    ...
```

---

## Implementation Checklist

### Phase 1: Team Context ✅ DONE (Feb 2026)
- [x] Add `get_team_context` via `api/middleware/tenant_context.py`
- [x] Auto-enable tenant headers when `AUTH_MODE=supabase_jwt`
- [x] All config endpoints use team-scoped `load_db()`/`save_db()`
- [x] Test with X-Team-Id header

**Implementation:** `TenantContextMiddleware` sets `CURRENT_TEAM_ID` contextvar, which `workflow_email.load_db()` uses via `get_team_id()`.

### Phase 2: Supabase Storage (Enables Persistence) 🔲 REQUIRED BEFORE INTEGRATION
- [ ] Create `ai_config` table in Supabase
- [ ] Add RLS policies
- [ ] Create `SupabaseConfigStorage` class
- [ ] Replace JSON storage calls with Supabase calls
- [ ] Add Supabase env vars to .env (see below)
- [ ] Enable `verify_team_membership()` in auth middleware
- [ ] Test config persistence across restarts

> **⚠️ BLOCKING FOR PRODUCTION:** This phase MUST be completed before frontend integration.
> The stub code for `verify_team_membership()` is ready in `api/middleware/auth.py`.
> See "Supabase Variables Required" section below for what you need from the dashboard.

### Phase 3: Auth Verification ✅ DONE (Feb 2026)
- [x] Add JWT verification middleware (`api/middleware/auth.py`)
- [x] Complete `_validate_supabase_jwt()` with PyJWT decode
- [x] Extract claims from `app_metadata` (Supabase convention)
- [x] Handle token_expired and invalid_token errors
- [x] Test with test JWT tokens

**Implementation:** `AuthMiddleware` validates JWT and sets `CURRENT_USER_ID`, `CURRENT_USER_ROLE`, and `CURRENT_TEAM_ID` contextvars.

### Phase 4: Admin Role Guard ✅ DONE (Feb 2026)
- [x] Add `require_admin_role()` helper
- [x] Apply to all 18 POST config endpoints
- [x] Returns 401 if not authenticated
- [x] Returns 403 if role not in (admin, owner)
- [x] Export from `api/middleware/__init__.py`

**Implementation:** Each POST handler calls `require_admin_role()` at the start.

### Phase 5: Full API Scoping (Future)
- [ ] Scope `/api/events` by team_id
- [ ] Scope `/api/tasks/*` by team_id
- [ ] Update activity logger to include team_id
- [ ] Test multi-tenant isolation

---

## Testing Strategy

### Local Testing (Current Test Frontend)
```bash
# Use X-Team-Id header
curl -H "X-Team-Id: test-team" http://localhost:8000/api/config/prompts
```

### Integration Testing (OpeneventGithub)
```bash
# Use Supabase token
TOKEN=$(get_supabase_token)  # From browser devtools or test script
curl -H "Authorization: Bearer $TOKEN" \
     -H "X-Team-Id: actual-team-uuid" \
     http://localhost:8000/api/config/prompts
```

### Production Testing
```bash
# Same as integration, but against Hostinger
curl -H "Authorization: Bearer $TOKEN" \
     -H "X-Team-Id: $TEAM_ID" \
     https://your-hostinger-backend.com/api/config/prompts
```

---

---

## Supabase Variables Required

### Where to Find Them

| Variable | Where in Supabase Dashboard | Description |
|----------|----------------------------|-------------|
| `SUPABASE_JWT_SECRET` | Settings → API → JWT Secret | Signs/verifies JWT tokens |
| `OE_SUPABASE_URL` | Settings → API → Project URL | `https://xxx.supabase.co` |
| `OE_SUPABASE_KEY` | Settings → API → `service_role` key | Backend writes (NOT anon!) |

### Multi-Tenant IDs (from your tables)

| Variable | Source | Description |
|----------|--------|-------------|
| `OE_TEAM_ID` | `teams` table | Your team's UUID |
| `OE_SYSTEM_USER_ID` | `auth.users` table | System user for automated writes |
| `OE_EMAIL_ACCOUNT_ID` | `email_accounts` table | Email integration UUID |

### Quick Copy Template

```bash
# Auth (REQUIRED)
SUPABASE_JWT_SECRET=your-jwt-secret-here

# Supabase Connection (REQUIRED for P2)
OE_SUPABASE_URL=https://igrfkpxebvuvfwogondx.supabase.co
OE_SUPABASE_KEY=your-service-role-key-here

# Multi-tenant IDs
OE_TEAM_ID=your-team-uuid
OE_SYSTEM_USER_ID=your-system-user-uuid
OE_EMAIL_ACCOUNT_ID=your-email-account-uuid
```

---

## Environment Variables Summary

### Development (.env)
```bash
# Current
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
PROMPTS_EDITOR_ENABLED=true

# Auth (optional in dev - set AUTH_ENABLED=0 to disable)
AUTH_ENABLED=0
```

### Staging (with auth testing)
```bash
# Enable auth for testing
AUTH_ENABLED=1
AUTH_MODE=supabase_jwt
SUPABASE_JWT_SECRET=<from Supabase Dashboard: Settings → API → JWT Secret>

# Tenant headers auto-enabled in JWT mode
# TENANT_HEADER_ENABLED=1  # Not needed when AUTH_MODE=supabase_jwt
```

### Production (/opt/openevent/.env)
```bash
# Required
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=AIza...
PROMPTS_EDITOR_ENABLED=true
ENV=prod

# Auth (REQUIRED in production)
AUTH_ENABLED=1
AUTH_MODE=supabase_jwt
SUPABASE_JWT_SECRET=<from Supabase Dashboard>

# For P2 (Supabase Storage) - add when implementing
# SUPABASE_URL=https://igrfkpxebvuvfwogondx.supabase.co
# SUPABASE_SERVICE_KEY=eyJ...  # Service role key for backend writes

# CORS
ALLOWED_ORIGINS=https://your-production-domain.com
```

---

---

## Security Considerations

### JWT Claims vs Database Verification

**Current Implementation (Trust JWT Claims):**
The backend trusts the `team_id` and `role` from the JWT's `app_metadata`. This is standard practice because:
- ✅ JWT is cryptographically signed by Supabase (can't be tampered)
- ✅ Fast - no DB round-trip on every request
- ✅ Simpler implementation

**Trade-off:**
- ⚠️ If a user is removed from a team, their JWT is still valid until it expires
- ⚠️ Role changes won't take effect until JWT refresh

### Option: Database Verification (P2 Enhancement)

For maximum security at integration time, P2 (Supabase Storage) can include real-time verification:

```python
# In api/middleware/auth.py (Future P2 enhancement)

async def verify_team_membership(user_id: str, team_id: str) -> str:
    """Verify user is still a member of team and return current role."""
    supabase = get_supabase_client()

    # Check team_members_new table
    result = await supabase.table("team_members_new")\
        .select("role")\
        .eq("team_id", team_id)\
        .eq("user_id", user_id)\
        .eq("invitation_status", "active")\
        .single()\
        .execute()

    if not result.data:
        # Check if user is team owner
        team = await supabase.table("teams")\
            .select("owner_id")\
            .eq("id", team_id)\
            .single()\
            .execute()

        if team.data and team.data["owner_id"] == user_id:
            return "owner"

        raise HTTPException(status_code=403, detail="Not a team member")

    return result.data["role"]
```

**Recommendation:**
1. **For initial integration:** Trust JWT claims (current implementation)
2. **For P2 (Supabase Storage):** Add optional DB verification behind feature flag
3. **For production launch:** Enable DB verification with caching (5-minute TTL)

```python
# Example with caching
@lru_cache(maxsize=1000, ttl=300)  # 5 min cache
async def get_verified_role(user_id: str, team_id: str) -> str:
    return await verify_team_membership(user_id, team_id)
```

---

## Notes

### Why X-Team-Id Header Still Works
The frontend sends both:
1. `Authorization: Bearer <supabase_token>` - For user identity
2. `X-Team-Id: <team_uuid>` - For selected team context

This is because a user can belong to multiple teams and switch between them. The selected team is tracked client-side and sent with each request.

### Backwards Compatibility
All changes should be backwards compatible:
- If no auth header, fall back to X-Team-Id header
- If no X-Team-Id, use "default" tenant
- Test frontend continues to work without Supabase tokens

---

## Related Documentation

- **Supabase Schema:** See `docs/integration/SUPABASE_INTEGRATION.md` for schema requirements and SQL scripts
