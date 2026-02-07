# Supabase Integration: Todo Steps

This document outlines the final steps to switch the OpenEvent-AI backend from local JSON storage to Supabase.

## 1. Environment Verification
Ensure your `.env` file in the project root is populated with valid UUIDs. 
Run the following to verify:
```bash
.venv/bin/python workflows/io/integration/test_connection.py
```
*Note: If you get a Pydantic error, use `fetch_supabase_ids.py` to confirm connection.*

## 2. Data Migration
Before switching the live system, migrate your existing JSON data to Supabase so the AI has access to current leads and events.
```bash
.venv/bin/python scripts/migrate_json_to_supabase.py
```
**Verify in Supabase Dashboard:**
- Check `clients` table for new entries.
- Check `events` table for new entries.

## 3. Enable Supabase Mode
Change the integration mode in your `.env` file:
```bash
OE_INTEGRATION_MODE=supabase
```

## 3.1 Country/Timezone Support (new)
To make workflow time handling country-sensitive, the backend now reads client country/timezone from the client account profile.

- If your `clients` table already has country/timezone fields, keep using those.
- If not, add them:

```sql
ALTER TABLE clients
ADD COLUMN IF NOT EXISTS country TEXT,
ADD COLUMN IF NOT EXISTS timezone TEXT;
```

Recommended:
- Store `timezone` as IANA names (example: `Europe/Zurich`, `America/New_York`).
- If only `country` is present, backend falls back to a country->default-timezone map.

## 4. Restart & Test Flow
1. **Start the Backend:** `npm run dev` (or your backend start command).
2. **Trigger a Lead:** Send a message that results in a new lead.
3. **Check Logs:** Look for Supabase insert logs.
4. **Verify Offer:** Generate an offer and ensure the `products` column in the Supabase `offers` table is populated.

## 5. Security Hardening (At Integration Time)

These steps must be completed on the **production branch** when integrating with Supabase/frontend — not on the development/testing branch.

- [ ] **AUTH-1** — Flip auth default to opt-out: change `AUTH_ENABLED` default from `0` to `1` in `api/middleware/auth.py` so forgetting the env var = protected
- [ ] **AUTH-2** — Add `@require_auth` guards to unprotected GET routes (`api/routes/events.py`, `api/routes/config.py`, `api/routes/messages.py`)
- [ ] **AUTH-3** — Replace `verify_team_membership()` stub with real Supabase RLS or database check in `api/middleware/auth.py`

> **Why deferred?** These are production-only concerns. On the dev/testing branch, auth is intentionally relaxed to allow rapid iteration without token overhead.

## 6. Maintenance
- The `scripts/migrate_json_to_supabase.py` can be run multiple times; it checks for existing records to avoid duplicates.
- All code changes are now in `workflows/io/integration/supabase_adapter.py`.
