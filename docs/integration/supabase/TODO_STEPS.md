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

## 4. Restart & Test Flow
1. **Start the Backend:** `npm run dev` (or your backend start command).
2. **Trigger a Lead:** Send a message that results in a new lead.
3. **Check Logs:** Look for Supabase insert logs.
4. **Verify Offer:** Generate an offer and ensure the `products` column in the Supabase `offers` table is populated.

## 5. Maintenance
- The `scripts/migrate_json_to_supabase.py` can be run multiple times; it checks for existing records to avoid duplicates.
- All code changes are now in `workflows/io/integration/supabase_adapter.py`.
