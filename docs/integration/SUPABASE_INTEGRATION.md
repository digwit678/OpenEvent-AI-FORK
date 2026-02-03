# Supabase Integration Guide

This document tracks the Supabase schema requirements for the OpenEvent-AI backend.

**Last schema check:** 2026-02-02

---

## Current Schema Status

### Tables That Match Backend Expectations

| Table | Expected Columns | Status |
|-------|------------------|--------|
| `clients` | id, name, email, team_id, user_id, status, company, phone | ✅ Complete |
| `tasks` | id, title, description, category, priority, team_id, event_id, client_name, status | ✅ Complete |
| `emails` | from_email, to_email, subject, body_text, event_id, client_id, is_sent, thread_id | ✅ Complete |
| `rooms` | id, name, team_id, capacity, amenities | ✅ Complete |
| `products` | id, name, team_id, available, base_price | ✅ Complete |
| `offers` | id, event_id, total_amount, deposit_enabled, products (JSONB) | ✅ Complete |
| `offer_line_items` | offer_id, team_id | ✅ Exists |
| `team_members_new` | team_id, user_id, role, invitation_status | ✅ Complete |
| `teams` | id, owner_id | ✅ Complete |

### Missing Schema (Requires Changes)

| Table | Column/Table | Type | Purpose | Priority |
|-------|--------------|------|---------|----------|
| `events` | `current_step` | INT | Workflow step (1-7) | **P1** |
| `events` | `date_confirmed` | BOOL | Date confirmation flag | **P1** |
| (new table) | `ai_config` | — | Team-scoped AI config | **P2** |

---

## Required Supabase Changes

### P1: Add Workflow State Columns to `events`

The backend's `supabase_adapter.py` expects these columns for workflow state sync.

**Run in Supabase Dashboard → SQL Editor:**

```sql
-- Add workflow state columns to events table
ALTER TABLE events
ADD COLUMN IF NOT EXISTS current_step INTEGER DEFAULT 1,
ADD COLUMN IF NOT EXISTS date_confirmed BOOLEAN DEFAULT FALSE;

-- Index for workflow queries (recommended)
CREATE INDEX IF NOT EXISTS idx_events_workflow_state
ON events(team_id, current_step, date_confirmed);

-- Documentation comments
COMMENT ON COLUMN events.current_step IS 'Workflow step: 1=intake, 2=date, 3=room, 4=offer, 5=negotiate, 6=contract, 7=confirm';
COMMENT ON COLUMN events.date_confirmed IS 'Whether the event date has been confirmed by the client';
```

**Verification:**
```sql
-- Check columns were added
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'events' AND column_name IN ('current_step', 'date_confirmed');
```

---

### P2: Create `ai_config` Table

Required for team-scoped AI configuration storage (prompts, settings, etc.).

**Run in Supabase Dashboard → SQL Editor:**

```sql
-- Create ai_config table for team-scoped AI settings
CREATE TABLE IF NOT EXISTS ai_config (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    team_id UUID NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    config_key TEXT NOT NULL,
    data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    UNIQUE(team_id, config_key)
);

-- Enable Row Level Security
ALTER TABLE ai_config ENABLE ROW LEVEL SECURITY;

-- Policy: Team members can read their team's config
CREATE POLICY "Team members can read config"
ON ai_config FOR SELECT
USING (
    team_id IN (
        SELECT team_id FROM team_members_new
        WHERE user_id = auth.uid() AND invitation_status = 'active'
    )
    OR team_id IN (
        SELECT id FROM teams WHERE owner_id = auth.uid()
    )
);

-- Policy: Only admins/owners can write config
CREATE POLICY "Admins can write config"
ON ai_config FOR ALL
USING (
    team_id IN (
        SELECT team_id FROM team_members_new
        WHERE user_id = auth.uid()
        AND invitation_status = 'active'
        AND role IN ('admin', 'owner')
    )
    OR team_id IN (
        SELECT id FROM teams WHERE owner_id = auth.uid()
    )
);

-- Index for fast lookups
CREATE INDEX IF NOT EXISTS idx_ai_config_team_key
ON ai_config(team_id, config_key);

-- Auto-update timestamp trigger
CREATE OR REPLACE FUNCTION update_ai_config_timestamp()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER ai_config_updated_at
BEFORE UPDATE ON ai_config
FOR EACH ROW EXECUTE FUNCTION update_ai_config_timestamp();
```

**Verification:**
```sql
-- Check table was created
SELECT table_name FROM information_schema.tables WHERE table_name = 'ai_config';

-- Check RLS is enabled
SELECT tablename, rowsecurity FROM pg_tables WHERE tablename = 'ai_config';
```

---

## Backend Environment Variables

These variables connect the backend to Supabase:

| Variable | Source | Required For |
|----------|--------|--------------|
| `OE_SUPABASE_URL` | Dashboard → Settings → API → Project URL | All Supabase operations |
| `OE_SUPABASE_KEY` | Dashboard → Settings → API → `service_role` key | Backend writes |
| `SUPABASE_JWT_SECRET` | Dashboard → Settings → API → JWT Secret | Auth verification |
| `OE_TEAM_ID` | Your `teams` table | Multi-tenant scoping |
| `OE_SYSTEM_USER_ID` | Your `auth.users` table | Automated writes |

**Example `.env`:**
```bash
OE_SUPABASE_URL=https://igrfkpxebvuvfwogondx.supabase.co
OE_SUPABASE_KEY=your-service-role-key
SUPABASE_JWT_SECRET=your-jwt-secret
OE_TEAM_ID=your-team-uuid
OE_SYSTEM_USER_ID=your-system-user-uuid
```

---

## Integration Mode

The backend supports two storage modes:

| Mode | Config | Storage |
|------|--------|---------|
| Local (default) | `OE_INTEGRATION_MODE=local` | JSON files |
| Supabase | `OE_INTEGRATION_MODE=supabase` | Supabase tables |

Set `OE_INTEGRATION_MODE=supabase` to enable Supabase storage.

---

## Backend Files That Use Supabase

| File | Purpose |
|------|---------|
| `workflows/io/integration/supabase_adapter.py` | Main Supabase operations (events, clients, tasks) |
| `workflows/io/integration/config.py` | Connection config and env vars |
| `workflows/io/integration/hil_tasks.py` | HIL task creation |
| `workflows/io/integration/uuid_adapter.py` | UUID generation and lookups |
| `api/middleware/auth.py` | JWT verification, membership stubs |

---

## Checklist: Before Going Live

- [ ] Run P1 SQL (workflow columns on `events`)
- [ ] Run P2 SQL (create `ai_config` table)
- [ ] Verify RLS policies work with test user
- [ ] Set env vars: `OE_SUPABASE_URL`, `OE_SUPABASE_KEY`
- [ ] Set `OE_INTEGRATION_MODE=supabase`
- [ ] Test: Events sync workflow state correctly
- [ ] Test: Config changes persist after restart
