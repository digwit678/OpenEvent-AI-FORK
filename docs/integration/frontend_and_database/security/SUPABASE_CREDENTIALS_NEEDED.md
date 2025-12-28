# Supabase Credentials Needed for AI Workflow Integration

**Send this to your co-founder who hosts the Supabase instance.**

---

## Required Credentials

| Variable | Description | Where to Find |
|----------|-------------|---------------|
| `OE_SUPABASE_URL` | Supabase project URL | Dashboard → Settings → API → Project URL |
| `OE_SUPABASE_KEY` | Supabase API key | Dashboard → Settings → API → `anon` or `service_role` key |
| `OE_TEAM_ID` | UUID of the team for this workflow | Query: `SELECT id, name FROM teams;` |
| `OE_SYSTEM_USER_ID` | UUID of user for automated writes | Query: `SELECT id, email FROM auth.users;` or create a system user |

### Optional (for email operations)
| Variable | Description | Where to Find |
|----------|-------------|---------------|
| `OE_EMAIL_ACCOUNT_ID` | UUID of email account for sending | Query: `SELECT id, email FROM email_accounts WHERE team_id = '<team_id>';` |

---

## What I Need From You

### 1. Supabase Connection Details

```
Project URL: https://____________.supabase.co
API Key: ___________________________________ (anon key is fine for testing)
```

**Location:** Supabase Dashboard → Settings → API

---

### 2. Team UUID

Run this query and send me the result:

```sql
SELECT id, name FROM teams;
```

I need the `id` (UUID) for the team the AI workflow should operate on.

---

### 3. System User UUID

Option A: Use an existing admin user
```sql
SELECT id, email FROM auth.users WHERE email LIKE '%admin%' OR email LIKE '%system%';
```

Option B: Create a dedicated system user for the AI workflow
```sql
-- You may need to create this via your auth flow, then get the ID
SELECT id, email FROM auth.users ORDER BY created_at DESC LIMIT 5;
```

I need a `user_id` that will be used as the author for all AI-created records.

---

### 4. (Optional) Email Account UUID

If email integration is needed:
```sql
SELECT id, email FROM email_accounts WHERE team_id = '<team_id>';
```

---

## Schema Additions Needed

**Before we can fully integrate, these columns need to be added:**

### On `events` table (MVP):
```sql
ALTER TABLE events ADD COLUMN IF NOT EXISTS current_step INT DEFAULT 1;
ALTER TABLE events ADD COLUMN IF NOT EXISTS date_confirmed BOOLEAN DEFAULT FALSE;
ALTER TABLE events ADD COLUMN IF NOT EXISTS caller_step INT;
```

### On `rooms` table (MVP):
```sql
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS deposit_required BOOLEAN DEFAULT FALSE;
ALTER TABLE rooms ADD COLUMN IF NOT EXISTS deposit_percent INT;
```

---

## Quick Test Queries

After you send me the credentials, I can run a test. You can also verify access by running:

```sql
-- Check team exists
SELECT * FROM teams WHERE id = '<team_id>';

-- Check we can read rooms
SELECT id, name FROM rooms WHERE team_id = '<team_id>' LIMIT 5;

-- Check we can read events
SELECT id, title, status FROM events WHERE team_id = '<team_id>' LIMIT 5;

-- Check we can read/write tasks
SELECT id, title, category FROM tasks WHERE team_id = '<team_id>' LIMIT 5;
```

---

## API Key Type

| Key Type | Use Case |
|----------|----------|
| `anon` key | Testing, respects Row Level Security (RLS) |
| `service_role` key | Backend operations, bypasses RLS |

For the AI workflow backend, **`service_role` key is recommended** since we're doing server-side operations and need to create records for any user.

⚠️ **Never expose `service_role` key in frontend code!**

---

## Example .env File

Once you have the values, I'll set them like this:

```bash
# Supabase Integration
export OE_INTEGRATION_MODE=supabase
export OE_SUPABASE_URL=https://xxxxx.supabase.co
export OE_SUPABASE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
export OE_TEAM_ID=550e8400-e29b-41d4-a716-446655440000
export OE_SYSTEM_USER_ID=660e8400-e29b-41d4-a716-446655440001
export OE_EMAIL_ACCOUNT_ID=770e8400-e29b-41d4-a716-446655440002
```

---

## Contact

Questions? Let me know what you need clarification on.