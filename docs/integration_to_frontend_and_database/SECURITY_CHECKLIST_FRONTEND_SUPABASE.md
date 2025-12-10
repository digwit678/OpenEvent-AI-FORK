# Security Checklist: Frontend & Supabase

**For:** Co-founder / Frontend Team
**Project:** OpenEvent AI Integration
**Date:** 2025-12-09

---

## Priority Overview

| Priority | Items | When to Fix |
|----------|-------|-------------|
| 🔴 **MVP BLOCKER** | RLS enabled, correct API key, login required | Before AI integration |
| 🟡 **MVP Recommended** | Cross-team isolation test, service_role protected | Before going live |
| 🟢 **Post-MVP** | Backups, session expiry, backup restore test | Within 1-2 weeks of launch |

---

## How to Use This Document

This checklist helps you verify that your Supabase and frontend setup is secure before we connect the AI workflow.

- **Go through each section** and answer the questions
- **Check the boxes** (Yes/No) as you verify each item
- **If unsure**, the "How to Check" column tells you exactly where to look
- **Red flags** are marked clearly — these need immediate attention

---

## Section 1: Data Isolation (Row Level Security)

**🔴 Priority: MVP BLOCKER**

**What is this?** Row Level Security (RLS) ensures users can only see their own team's data. Without it, any logged-in user could see ALL data from ALL teams.

**Risk if not done:** User A can see User B's private event details, client information, and financial data.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 1.1 | Is RLS enabled for `events` table? | Supabase Dashboard → Table Editor → Select "events" → Look for "RLS enabled" badge | ⬜ Yes  ⬜ No |
| 1.2 | Is RLS enabled for `clients` table? | Same steps for "clients" table | ⬜ Yes  ⬜ No |
| 1.3 | Is RLS enabled for `tasks` table? | Same steps for "tasks" table | ⬜ Yes  ⬜ No |
| 1.4 | Is RLS enabled for `offers` table? | Same steps for "offers" table | ⬜ Yes  ⬜ No |
| 1.5 | Is RLS enabled for `emails` table? | Same steps for "emails" table | ⬜ Yes  ⬜ No |
| 1.6 | Is RLS enabled for `rooms` table? | Same steps for "rooms" table | ⬜ Yes  ⬜ No |
| 1.7 | Is RLS enabled for `products` table? | Same steps for "products" table | ⬜ Yes  ⬜ No |

### Quick Visual Guide

In Supabase Dashboard, go to Table Editor and select a table. You should see:

```
✅ GOOD: "RLS enabled" badge visible
❌ BAD:  "RLS disabled" or no badge
```

### What To Do If RLS Is Off

Ask your developer to enable RLS and create policies. Example SQL:

```sql
-- Enable RLS on events table
ALTER TABLE events ENABLE ROW LEVEL SECURITY;

-- Create policy: users can only see their team's events
CREATE POLICY "Team members can view own events"
ON events FOR SELECT
USING (team_id IN (
  SELECT team_id FROM team_members WHERE user_id = auth.uid()
));
```

**Estimated fix time:** 1-3 days depending on number of tables

---

## Section 2: API Key Security

**🔴 Priority: MVP BLOCKER**

**What is this?** Supabase provides two API keys:
- `anon` key: Safe for frontend (browser), respects RLS rules
- `service_role` key: Dangerous for frontend, bypasses ALL security

**Risk if wrong key used:** If `service_role` key is in frontend code, hackers can extract it and gain full access to your entire database.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 2.1 | Which key is in your frontend code? | Search frontend codebase for "supabase" and find the key being used | ⬜ anon (safe)  ⬜ service_role (DANGER!) |
| 2.2 | Is `service_role` key in any public file? | Search for your service_role key value in all code | ⬜ Not found (good)  ⬜ Found (FIX NOW!) |
| 2.3 | Is the `service_role` key in `.env` file that's gitignored? | Check `.gitignore` includes `.env` files | ⬜ Yes  ⬜ No |
| 2.4 | Is `service_role` key in any git history? | Run: `git log -p | grep "service_role"` | ⬜ Not found  ⬜ Found (rotate key!) |

### Where to Find Your Keys

Supabase Dashboard → Settings → API

You'll see:
- **Project URL:** `https://xxxxx.supabase.co`
- **anon / public:** `eyJhbGci...` (this is OK for frontend)
- **service_role:** `eyJhbGci...` (NEVER put this in frontend!)

### Key Rules

| Key | Where It Can Be Used | Safe in Browser? |
|-----|---------------------|------------------|
| `anon` | Frontend JavaScript, mobile apps | ✅ Yes |
| `service_role` | Backend servers ONLY | ❌ NO - NEVER! |

### Red Flag Test

Open your app in browser → Press F12 → Network tab → Refresh → Click any Supabase request → Look at Headers

- ✅ **Safe:** `apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...` (this is anon key)
- ❌ **Danger:** If you can access all data without restrictions, service_role key might be exposed

---

## Section 3: User Authentication

**🔴 Priority: MVP BLOCKER** (3.1, 3.3) | **🟢 Post-MVP** (3.2, 3.4)

**What is this?** Ensures only logged-in users can access the app, and they can only see data they're authorized to see.

**Risk if not done:** Anyone on the internet could access your business data.

### Checklist

| # | Question | How to Check | Priority | Status |
|---|----------|--------------|----------|--------|
| 3.1 | Must users log in to use the app? | Open app in incognito browser - should redirect to login | 🔴 MVP | ⬜ Yes  ⬜ No |
| 3.2 | Is authentication using Supabase Auth? | Check your login code | 🟢 Later | ⬜ Supabase Auth  ⬜ Other  ⬜ None |
| 3.3 | Are user sessions validated? | Log out, try to access a protected page directly | 🔴 MVP | ⬜ Blocked  ⬜ Allowed (bad!) |
| 3.4 | Do sessions expire? | Leave app open overnight, check if still logged in | 🟢 Later | ⬜ Expires  ⬜ Never expires |

### Cross-Team Data Test

**🟡 Priority: MVP Recommended**

This is the most important test:

1. Create two test users in different teams (Team A and Team B)
2. Log in as Team A user
3. Create a test event
4. Log out
5. Log in as Team B user
6. **Check:** Can you see Team A's event?

| Result | Status |
|--------|--------|
| Team B cannot see Team A's data | ✅ SECURE |
| Team B CAN see Team A's data | ❌ FIX IMMEDIATELY - RLS not working |

---

## Section 4: Data Backups

**🟢 Priority: Post-MVP** (nice to have, fix within 1-2 weeks of launch)

**What is this?** Regular backups protect against accidental deletion, bugs, or disasters.

**Risk if not done:** If something goes wrong, all your data could be permanently lost.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 4.1 | Are automatic backups enabled? | Supabase Dashboard → Settings → Database → Backups | ⬜ Yes  ⬜ No |
| 4.2 | Backup frequency? | Same location | ⬜ Daily  ⬜ Weekly  ⬜ Other: _____ |
| 4.3 | Backup retention period? | Same location | _____ days |
| 4.4 | Has restore been tested? | Ask developer if they've ever restored from backup | ⬜ Yes  ⬜ No  ⬜ Unknown |

### Supabase Backup Tiers

| Plan | Backup Frequency | Point-in-Time Recovery |
|------|------------------|------------------------|
| Free | Daily | No |
| Pro | Daily | Yes (7 days) |
| Team | Daily | Yes (14 days) |
| Enterprise | Custom | Yes (custom) |

---

## Section 5: Quick Self-Test (2 Minutes)

Do this yourself right now:

### Test A: Check What's Exposed in Browser

1. Open your app in Chrome/Firefox
2. Press **F12** (or right-click → Inspect)
3. Go to **Network** tab
4. Refresh the page
5. Look for requests to `supabase.co`
6. Click on any request
7. Look at **Headers** section

**What you should see:**
```
apikey: eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6...
```

This is the `anon` key - that's fine.

**Red flag:** If the response contains all data without filtering, something is wrong.

### Test B: Incognito Access Test

1. Open a new **incognito/private** browser window
2. Go to your app URL
3. Try to access any page with data (like /events or /clients)

**Expected:** Redirected to login page
**Red flag:** Can see data without logging in

### Test C: Direct API Test

1. Open a new browser tab
2. Go to: `https://YOUR-PROJECT.supabase.co/rest/v1/events`
3. You should see an error (no access)

**Expected:** Error message about missing/invalid key
**Red flag:** Returns actual data

---

## Section 6: Summary Scorecard

Fill this in after completing the checklist:

| Category | Status | Risk Level | Action Needed |
|----------|--------|------------|---------------|
| **RLS Enabled (all tables)** | ⬜ Pass  ⬜ Fail | Critical | |
| **Correct API Key in Frontend** | ⬜ Pass  ⬜ Fail | Critical | |
| **Service Role Key Protected** | ⬜ Pass  ⬜ Fail | Critical | |
| **Login Required** | ⬜ Pass  ⬜ Fail | Critical | |
| **Cross-Team Isolation** | ⬜ Pass  ⬜ Fail | Critical | |
| **Backups Enabled** | ⬜ Pass  ⬜ Fail | High | |
| **Backup Tested** | ⬜ Pass  ⬜ Fail | Medium | |

### Overall Security Status

| All Critical Items Pass? | Ready for Integration? |
|--------------------------|------------------------|
| ✅ Yes | ✅ Ready to proceed |
| ❌ No | ❌ Fix critical items first |

---

## Section 7: For Your Developer

If you need help, share these SQL queries with your developer:

### Check RLS Status

```sql
-- Run this in Supabase SQL Editor
SELECT
  schemaname,
  tablename,
  rowsecurity as "RLS Enabled"
FROM pg_tables
WHERE schemaname = 'public'
ORDER BY tablename;
```

**Expected:** All main tables show `true` in "RLS Enabled" column.

### Check RLS Policies

```sql
-- See what policies exist
SELECT
  tablename,
  policyname,
  permissive,
  cmd as "Operation"
FROM pg_policies
WHERE schemaname = 'public'
ORDER BY tablename, policyname;
```

**Expected:** Each table should have policies for SELECT, INSERT, UPDATE, DELETE.

### Check for Exposed Keys in Code

```bash
# Run in your frontend project folder
grep -r "service_role" --include="*.js" --include="*.ts" --include="*.jsx" --include="*.tsx" .
```

**Expected:** No results (service_role key should not appear anywhere in frontend code).

---

## Questions?

If you're unsure about any item:

1. **Mark it as "Unknown"** in the checklist
2. **Share this document** with your developer
3. **Ask them to verify** and fill in the answers

Security issues should be fixed **before** connecting the AI workflow to your production database.

---

*Document version: 1.0 | Created: 2025-12-09*