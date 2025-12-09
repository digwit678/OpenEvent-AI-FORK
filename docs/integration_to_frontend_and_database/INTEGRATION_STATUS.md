# Integration Status Tracker

**Last Updated:** 2025-12-09
**Reference:** `EMAIL_WORKFLOW_INTEGRATION_REQUIREMENTS.md`

---

## Overall Progress

```
Backend Prep:     ████████████████████ 100%
Supabase Schema:  ░░░░░░░░░░░░░░░░░░░░   0%  (waiting on co-founder)
Connection Test:  ░░░░░░░░░░░░░░░░░░░░   0%  (waiting on credentials)
Communication:    ░░░░░░░░░░░░░░░░░░░░   0%  (waiting on decisions)
```

---

## Part A: Workflow Code Changes (OUR SIDE)

### A1. Column Name Mappings
| Mapping | Status | File |
|---------|--------|------|
| `organization` → `company` | ✅ Done | `field_mapping.py` |
| `chosen_date` → `event_date` | ✅ Done | `field_mapping.py` |
| `number_of_participants` → `attendees` | ✅ Done | `field_mapping.py` |
| `capacity_max` → `capacity` | ✅ Done | `field_mapping.py` |
| Task `type` → `category` | ✅ Done | `field_mapping.py` |
| `resolved_at` → `completed_at` | ✅ Done | `field_mapping.py` |
| `deposit_paid` → `deposit_paid_at` | ✅ Done | `field_mapping.py` |
| `deposit_status` → `payment_status` | ✅ Done | `field_mapping.py` |
| `accepted_at` → `confirmed_at` | ✅ Done | `field_mapping.py` |

### A2. ID Format Changes (UUID)
| Item | Status | File |
|------|--------|------|
| Client lookup by email → UUID | ✅ Done | `uuid_adapter.py` |
| Room slug → UUID registry | ✅ Done | `uuid_adapter.py` |
| Product slug → UUID registry | ✅ Done | `uuid_adapter.py` |
| UUID validation | ✅ Done | `uuid_adapter.py` |
| UUID caching | ✅ Done | `uuid_adapter.py` |

### A3. Array Format Changes
| Item | Status | File |
|------|--------|------|
| `locked_room_id` → `room_ids[]` | ✅ Done | `field_mapping.py` |
| `features` → `amenities[]` | ✅ Done | `field_mapping.py` |
| `equipment` → `amenities[]` | ✅ Done | `field_mapping.py` |

### A4. Required Fields for Record Creation
| Entity | Required Fields | Status | File |
|--------|-----------------|--------|------|
| Clients | name, team_id, user_id | ✅ Done | `supabase_adapter.py` |
| Events | title, event_date, start_time, end_time, team_id, user_id | ✅ Done | `supabase_adapter.py` |
| Offers | offer_number, subject, offer_date, user_id | ✅ Done | `supabase_adapter.py` |
| Offer Line Items | offer_id, name, quantity, unit_price, total | ✅ Done | `offer_utils.py` |
| Tasks | title, category, team_id, user_id | ✅ Done | `hil_tasks.py` |
| Emails | from_email, to_email, subject, body_text, team_id, user_id | ✅ Done | `hil_tasks.py` |

### A5. Offer Number Generation
| Item | Status | File |
|------|--------|------|
| Format: `OE-2025-12-XXXX` | ✅ Done | `offer_utils.py` |
| Unique short ID generation | ✅ Done | `offer_utils.py` |

### A6. Room Capacity Mapping
| Layout | Supabase Column | Status | File |
|--------|-----------------|--------|------|
| `theatre` | `theater_capacity` | ✅ Done | `field_mapping.py` |
| `cocktail` | `cocktail_capacity` | ✅ Done | `field_mapping.py` |
| `dinner` | `seated_dinner_capacity` | ✅ Done | `field_mapping.py` |
| `standing` | `standing_capacity` | ✅ Done | `field_mapping.py` |
| Default | `capacity` | ✅ Done | `field_mapping.py` |

### A7. Product Category Handling
| Item | Status | File |
|------|--------|------|
| Category UUID lookup | ✅ Skeleton | `supabase_adapter.py` |
| Filter by name pattern | ✅ Ready | N/A |

### A8. Status Values (Capitalization)
| Internal | Supabase | Status | File |
|----------|----------|--------|------|
| `Lead` | `lead` | ✅ Done | `status_utils.py` |
| `Option` | `option` | ✅ Done | `status_utils.py` |
| `Confirmed` | `confirmed` | ✅ Done | `status_utils.py` |
| `Cancelled` | `cancelled` | ✅ Done | `status_utils.py` |
| `Draft` | `draft` | ✅ Done | `status_utils.py` |
| `Sent` | `sent` | ✅ Done | `status_utils.py` |

### A9. Timezone Handling
| Item | Status | File |
|------|--------|------|
| Europe/Zurich default | ✅ Done | `offer_utils.py` |
| Date formatting (YYYY-MM-DD) | ✅ Done | `offer_utils.py` |
| Time formatting (HH:MM:SS) | ✅ Done | `supabase_adapter.py` |

---

## Part B: Supabase Schema Changes (CO-FOUNDER SIDE)

### B1. Rooms Table (MVP)
| Column | Type | Status |
|--------|------|--------|
| `deposit_required` | BOOLEAN | ⏳ Waiting |
| `deposit_percent` | INT | ⏳ Waiting |

### B2. Events Table (MVP)
| Column | Type | Status |
|--------|------|--------|
| `current_step` | INT DEFAULT 1 | ⏳ Waiting |
| `date_confirmed` | BOOLEAN DEFAULT FALSE | ⏳ Waiting |
| `caller_step` | INT | ⏳ Waiting |

### B3. Events Table (LATER)
| Column | Type | Status |
|--------|------|--------|
| `seating_layout` | TEXT | ⏳ Later |
| `preferred_room` | TEXT | ⏳ Later |
| `requirements_hash` | TEXT | ⏳ Later |
| `room_eval_hash` | TEXT | ⏳ Later |
| `offer_hash` | TEXT | ⏳ Later |

### B4. New Tables (LATER)
| Table | Status |
|-------|--------|
| `site_visits` | ⏳ Later |
| `page_snapshots` | ⏳ Later |
| `client_preference_history` | ⏳ Later |

---

## Part C: Existing Features (No Changes Needed)

| Feature | Status |
|---------|--------|
| Deposit fields on `offers` table | ✅ Already exists |
| `emails` table for conversation history | ✅ Already exists |

---

## Part D: Configuration

| Config | Status | Notes |
|--------|--------|-------|
| `OE_TEAM_ID` | ⏳ Waiting | Need from co-founder |
| `OE_SYSTEM_USER_ID` | ⏳ Waiting | Need from co-founder |
| `OE_EMAIL_ACCOUNT_ID` | ⏳ Waiting | Optional, for email ops |
| `OE_SUPABASE_URL` | ⏳ Waiting | Need from co-founder |
| `OE_SUPABASE_KEY` | ⏳ Waiting | Need from co-founder |

---

## Part E: Critical MVP Requirements

### HIL for Every Message
| Item | Status |
|------|--------|
| Task template for message approval | ✅ Done |
| Task template for offer approval | ✅ Done |
| Task template for date confirmation | ✅ Done |
| Task template for room approval | ✅ Done |
| Task template for manual review | ✅ Done |
| Task template for event confirmation | ✅ Done |
| **How frontend notifies backend of approval** | ❓ Open question |

---

## Infrastructure Created

| File | Purpose | Status |
|------|---------|--------|
| `integration/__init__.py` | Module exports | ✅ Done |
| `integration/config.py` | Toggle + env config | ✅ Done |
| `integration/field_mapping.py` | Column translations | ✅ Done |
| `integration/uuid_adapter.py` | UUID handling | ✅ Done |
| `integration/status_utils.py` | Status normalization | ✅ Done |
| `integration/offer_utils.py` | Offer formatting | ✅ Done |
| `integration/hil_tasks.py` | HIL task templates | ✅ Done |
| `integration/supabase_adapter.py` | Supabase operations | ✅ Done |
| `integration/adapter.py` | JSON/Supabase switcher | ✅ Done |
| `integration/test_connection.py` | Connection test script | ✅ Done |

---

## Open Questions (Awaiting Co-Founder Response)

### Communication Flow
1. **HIL Approval Flow** — How does frontend notify backend when manager approves a message?
   - Option A: Frontend calls our backend API
   - Option B: We poll Supabase for task status changes
   - Option C: Supabase webhook to our backend

2. **Incoming Email Trigger** — How does new client email trigger our workflow?
   - Option A: Frontend calls our API
   - Option B: Email webhook hits our backend
   - Option C: We poll `emails` table

3. **Real-time Updates** — How does frontend know when AI creates a task?
   - Option A: Supabase Realtime subscriptions
   - Option B: Frontend polling
   - Option C: WebSocket from our backend

---

## Frontend Compatibility

### Code Changes Required: NONE

The frontend already reads from Supabase. We write to the **same tables** in the **same format**.

| Table | Frontend Uses | We Write To | Compatible |
|-------|---------------|-------------|------------|
| `clients` | ✅ Yes | ✅ Yes | ✅ Same format |
| `events` | ✅ Yes | ✅ Yes | ✅ Same format |
| `tasks` | ✅ Yes | ✅ Yes | ✅ Same format |
| `offers` | ✅ Yes | ✅ Yes | ✅ Same format |
| `emails` | ✅ Yes | ✅ Yes | ✅ Same format |
| `rooms` | ✅ Yes (reads) | ❌ We only read | ✅ N/A |

### Minor Polish (Post-MVP)

| Item | Issue | Impact | Priority |
|------|-------|--------|----------|
| Task `payload` rendering | Frontend may not display our payload fields (draft_message, conflict_info) | Tasks appear but details may not render nicely | Low |
| New event columns | `current_step`, `date_confirmed` not displayed | No impact - internal workflow state | None |

---

## Security Considerations

### Our Backend (MVP Security Checklist)

| Item | Status | Priority | Notes |
|------|--------|----------|-------|
| **API Key Storage** | ✅ Done | Critical | Keys in env vars, not in code |
| **No hardcoded secrets** | ✅ Done | Critical | All credentials via environment |
| **Input validation on API endpoints** | ⚠️ Partial | High | FastAPI validates types, but add business logic validation |
| **Rate limiting** | ❌ Not done | Medium | Add rate limiting before production |
| **SQL injection protection** | ✅ N/A | N/A | Supabase client handles parameterization |
| **XSS protection** | ✅ N/A | N/A | No HTML rendering in backend |
| **CORS configuration** | ⚠️ Review | Medium | Check `backend/main.py` CORS settings |
| **Logging sensitive data** | ⚠️ Review | Medium | Ensure no PII/secrets in logs |
| **Error message leakage** | ⚠️ Review | Medium | Don't expose internal errors to clients |

#### Backend Security TODO (Before Production)

```python
# 1. Add rate limiting (e.g., slowapi)
# pip install slowapi
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)

# 2. Review CORS - restrict origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://your-frontend-domain.com"],  # Not "*"
    ...
)

# 3. Add request validation middleware
# - Validate team_id belongs to authenticated user
# - Validate event_id belongs to team

# 4. Audit logging
# - Log all write operations with user/team context
# - Log failed authentication attempts
```

**Estimated effort:** 1-2 days

---

### Frontend / Supabase Security (Co-Founder's Side)

#### Security Checklist for Co-Founder

**Please answer YES/NO to each question. If unsure, ask your developer to check.**

---

**1. DATA ISOLATION (Critical - prevents users seeing other teams' data)**

| Question | How to Check | Answer |
|----------|--------------|--------|
| Is Row Level Security (RLS) turned ON for the `events` table? | Supabase Dashboard → Table Editor → events → click "RLS" button → should say "RLS enabled" | ⬜ Yes / ⬜ No |
| Is RLS turned ON for the `clients` table? | Same as above for clients table | ⬜ Yes / ⬜ No |
| Is RLS turned ON for the `tasks` table? | Same as above for tasks table | ⬜ Yes / ⬜ No |
| Is RLS turned ON for the `offers` table? | Same as above for offers table | ⬜ Yes / ⬜ No |
| Is RLS turned ON for the `emails` table? | Same as above for emails table | ⬜ Yes / ⬜ No |
| Is RLS turned ON for the `rooms` table? | Same as above for rooms table | ⬜ Yes / ⬜ No |

**Why this matters:** If RLS is OFF, any logged-in user can see ALL data from ALL teams. With RLS ON, users only see their own team's data.

---

**2. API KEY SECURITY (Critical - prevents unauthorized access)**

| Question | How to Check | Answer |
|----------|--------------|--------|
| Which API key is used in the frontend code? | Search frontend code for "supabase" - should find `anon` key, NOT `service_role` | ⬜ anon / ⬜ service_role |
| Is the `service_role` key stored anywhere in frontend/public code? | Search all frontend files for the service_role key value - should find NOTHING | ⬜ Not found (good) / ⬜ Found (bad!) |

**Why this matters:** The `service_role` key bypasses ALL security. If it's in frontend code, anyone can extract it and access everything.

**Rule:**
- ✅ `anon` key = OK for frontend (browser)
- ✅ `service_role` key = OK for backend only (our Python server)
- ❌ `service_role` key in frontend = SECURITY HOLE

---

**3. USER AUTHENTICATION (Critical - ensures only real users access the system)**

| Question | How to Check | Answer |
|----------|--------------|--------|
| Do users have to log in to access the app? | Try opening the app in incognito - should redirect to login | ⬜ Yes / ⬜ No |
| Is the login using Supabase Auth? | Check if login goes through Supabase | ⬜ Yes / ⬜ Other |
| Can users only see their own team's data after login? | Log in as Team A user, check if Team B data is visible | ⬜ Isolated / ⬜ Can see other teams |

---

**4. BACKUPS (Medium - protects against data loss)**

| Question | How to Check | Answer |
|----------|--------------|--------|
| Are automatic backups enabled? | Supabase Dashboard → Settings → Database → Backups | ⬜ Yes / ⬜ No |
| How often are backups made? | Same location | Daily / Weekly / _____ |
| Has a backup restore ever been tested? | Ask your developer | ⬜ Yes / ⬜ No |

---

**5. QUICK SECURITY TEST (Do this yourself in 2 minutes)**

1. Open the app in your browser
2. Open Developer Tools (F12 or right-click → Inspect)
3. Go to "Network" tab
4. Refresh the page
5. Look for requests to `supabase.co`
6. Click on one and look at "Headers"

**Check:** The `apikey` header should be a long string starting with `eyJ...`. This is the `anon` key (safe).

**Red flag:** If you see a different key that gives you access to everything, that's the `service_role` key in the frontend (dangerous).

---

#### Summary for Non-Technical Review

| Area | What Could Go Wrong | How Bad | Easy to Check? |
|------|---------------------|---------|----------------|
| RLS Off | User A sees User B's private event data | Very Bad | Yes - Supabase Dashboard |
| Wrong API Key | Hackers get full database access | Critical | Yes - Browser Dev Tools |
| No Login | Anyone on internet can access data | Critical | Yes - Try incognito |
| No Backups | All data lost if something breaks | Bad | Yes - Supabase Dashboard |

---

#### If You Need Help

Ask your developer to run these SQL queries in Supabase SQL Editor:

```sql
-- Check which tables have RLS enabled
SELECT tablename, rowsecurity
FROM pg_tables
WHERE schemaname = 'public';

-- Check existing RLS policies
SELECT tablename, policyname, cmd, qual
FROM pg_policies
WHERE schemaname = 'public';
```

**Expected result:** All main tables (events, clients, tasks, offers, emails, rooms) should show `rowsecurity = true` and have policies listed.

**Estimated effort (their side):**
- If RLS already enabled: ✅ Just verify (30 min)
- If RLS needs to be added: 1-3 days of developer work

---

## MVP Security Summary

| Area | Our Side | Their Side |
|------|----------|------------|
| Critical items | 0 remaining | RLS policies (unknown) |
| High priority | Rate limiting, input validation | API key management |
| Medium priority | CORS, logging review | Backup strategy |
| Estimated effort | 1-2 days | 1-3 days |

---

## Next Steps

1. ⏳ **Wait for co-founder** to provide credentials and add schema columns
2. ⏳ **Run test script** once credentials received: `python backend/workflows/io/integration/test_connection.py`
3. ⏳ **Decide communication flow** based on co-founder's answers
4. ⏳ **Test end-to-end** with real Supabase data
5. ⏳ **Flip toggle** `OE_INTEGRATION_MODE=supabase` when ready
6. ⏳ **Security hardening** before production (rate limiting, CORS, validation)

---

## Files Reference

All integration code is in: `backend/workflows/io/integration/`

Documentation:
- `docs/integration_to_frontend_and_database/EMAIL_WORKFLOW_INTEGRATION_REQUIREMENTS.md`
- `docs/integration_to_frontend_and_database/FRONTEND_REFERENCE.md`
- `docs/integration_to_frontend_and_database/SUPABASE_CREDENTIALS_NEEDED.md`
- `docs/integration_to_frontend_and_database/INTEGRATION_STATUS.md` (this file)

---

*Updated by: Claude Code*