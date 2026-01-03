# Multi-Tenancy Production Deployment Guide

**Last Updated:** 2026-01-03

## Overview

OpenEvent AI supports multi-tenancy, allowing multiple teams/venues to share the same backend while keeping data completely isolated. Each team has its own:
- Clients
- Events
- Tasks
- Rooms
- Products
- Offers

## Production Deployment Checklist

### 1. Environment Variables

Set these in your Hostinger/production environment:

```bash
# Required for multi-tenancy
TENANT_HEADER_ENABLED=1              # Enable tenant header parsing

# Fallback values (used when no headers provided)
OE_TEAM_ID=your-default-team-uuid    # Default team UUID
OE_SYSTEM_USER_ID=your-user-uuid     # Default system user UUID
OE_EMAIL_ACCOUNT_ID=your-email-uuid  # Default email account UUID (if needed)
```

### 2. Supabase RLS Migration

**Before deploying to production, run this migration:**

File: `supabase/migrations/20260103000000_enable_rls_team_isolation.sql`

```bash
# Via Supabase CLI
supabase db push

# Or via SQL Editor in Supabase Dashboard
# Copy contents of the migration file and execute
```

**What the migration does:**
- Enables Row-Level Security on 8 tables
- Creates team isolation policies using `current_setting('app.team_id')`
- Creates service_role bypass policies (backend uses this)
- Adds performance indexes on `team_id` columns

**Tables affected:**
- `clients`
- `events`
- `tasks`
- `emails`
- `rooms`
- `products`
- `offers`
- `offer_line_items`

### 3. Verify team_id Columns Exist

Before running RLS migration, ensure all tables have a `team_id` column:

```sql
-- Check if team_id exists on each table
SELECT table_name, column_name
FROM information_schema.columns
WHERE column_name = 'team_id'
AND table_schema = 'public';
```

If missing, add with:
```sql
ALTER TABLE table_name ADD COLUMN team_id UUID;
CREATE INDEX idx_table_name_team_id ON table_name(team_id);
```

### 4. Backfill Existing Records

For existing production data without `team_id`:

```sql
-- Set team_id for all existing records to your default team
UPDATE clients SET team_id = 'your-team-uuid' WHERE team_id IS NULL;
UPDATE events SET team_id = 'your-team-uuid' WHERE team_id IS NULL;
UPDATE tasks SET team_id = 'your-team-uuid' WHERE team_id IS NULL;
-- Repeat for other tables
```

---

## API Integration

### Required Headers for Multi-Tenancy

All API requests must include tenant headers:

| Header | Type | Required | Description |
|--------|------|----------|-------------|
| `X-Team-Id` | string | Yes | Team/venue UUID |
| `X-Manager-Id` | string | Optional | Current manager/user UUID |

### Example API Calls

```bash
# Start conversation with tenant headers
curl -X POST http://your-backend/api/start-conversation \
  -H "Content-Type: application/json" \
  -H "X-Team-Id: team-abc-123" \
  -H "X-Manager-Id: manager-xyz-789" \
  -d '{"email_body":"Book room for 20 people...", ...}'

# Get pending tasks for a specific team
curl http://your-backend/api/tasks/pending \
  -H "X-Team-Id: team-abc-123"

# All other API calls follow the same pattern
```

### Frontend Integration

The frontend must send these headers with every API request:

```typescript
// Example: Set headers globally
const tenantHeaders = {
  'X-Team-Id': currentTeamId,
  'X-Manager-Id': currentManagerId
};

// Include in all fetch calls
fetch('/api/endpoint', {
  headers: {
    'Content-Type': 'application/json',
    ...tenantHeaders
  }
});
```

---

## How It Works

### Request Flow

```
1. Frontend sends request with X-Team-Id header
   ↓
2. TenantContextMiddleware extracts header
   ↓
3. Stores in contextvar (CURRENT_TEAM_ID)
   ↓
4. get_team_id() reads from contextvar
   ↓
5. All database queries filter by team_id
   ↓
6. RLS policies enforce isolation (defense-in-depth)
```

### Data Isolation Layers

| Layer | Mechanism | What it does |
|-------|-----------|--------------|
| 1 | Middleware | Extracts tenant from request headers |
| 2 | Contextvar | Stores tenant for request scope |
| 3 | Config | `get_team_id()` reads contextvar |
| 4 | Adapter | All queries include `team_id` filter |
| 5 | RLS | PostgreSQL enforces at database level |

---

## Testing Multi-Tenancy

### Quick Verification

```bash
# Create event as Team A
curl -X POST http://localhost:8000/api/start-conversation \
  -H "X-Team-Id: team-a" \
  -H "Content-Type: application/json" \
  -d '{"email_body":"Test from Team A","from_email":"a@test.com",...}'

# Try to access as Team B - should NOT see Team A's data
curl http://localhost:8000/api/tasks/pending \
  -H "X-Team-Id: team-b"
# Expected: {"tasks": []}  (empty - Team B has no tasks)

# Access as Team A - SHOULD see the task
curl http://localhost:8000/api/tasks/pending \
  -H "X-Team-Id: team-a"
# Expected: {"tasks": [...]}  (has Team A's tasks)
```

### JSON Mode (Development)

In development with `OE_INTEGRATION_MODE=json`:
- Each team gets a separate file: `events_{team_id}.json`
- Files created automatically on first request
- Full isolation between teams

### Supabase Mode (Production)

In production with `OE_INTEGRATION_MODE=supabase`:
- All data in single database
- Isolation via `team_id` column + RLS policies
- Backend uses service_role (bypasses RLS)
- Future: Client connections use anon key (RLS enforced)

---

## Troubleshooting

### "Team ID not found" errors

1. Check `TENANT_HEADER_ENABLED=1` is set
2. Verify headers are being sent from frontend
3. Check for header case sensitivity (`X-Team-Id` not `x-team-id`)

### Cross-tenant data leakage

1. Verify RLS policies are enabled: `SELECT * FROM pg_policies;`
2. Check all adapter functions include `.eq("team_id", team_id)`
3. Run test: create as Team A, query as Team B

### Missing team_id on new records

1. Check `get_team_id()` is returning the correct value
2. Verify headers are reaching the backend (log them)
3. Check contextvar is being set in middleware

---

## Files Reference

| File | Purpose |
|------|---------|
| `backend/api/middleware/tenant_context.py` | Header extraction middleware |
| `backend/workflows/io/integration/config.py` | `get_team_id()` function |
| `backend/workflows/io/integration/supabase_adapter.py` | Database operations with team_id |
| `supabase/migrations/20260103000000_enable_rls_team_isolation.sql` | RLS policies |
| `docs/reports/MULTI_TENANCY_PLAN_2026_01_03.md` | Full implementation details |
