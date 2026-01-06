# Plan: Update Hostinger Backend from Refactoring Branch

**Objective:** Update the `backend/` folder on the `integration/hostinger-backend` branch with the latest changes from `refactoring/17_12_25`, ensuring that:
1.  The new modular file structure (routes, etc.) is applied.
2.  The Hostinger-specific configuration (specifically `backend/.env`, which contains the API keys and is tracked on that branch) is **preserved**. See: docs/integration/frontend_and_database/specs/HOSTINGER_CONFIG_REFERENCE.md
3.  The process is automated with minimal manual intervention.
4.  **No push ever breaks production code or causes errors for customers.**

## Prerequisites
- You are currently on the `refactoring/17_12_25` branch.
- You have committed or stashed your current changes (workspace is clean).
- All tests pass on the refactoring branch before syncing.

## Execution Steps

Run the following commands in your terminal:

```bash
# 1. Ensure your current work is saved
git add .
git commit -m "Save point: Work in progress"

# 2. Switch to the Hostinger branch
git checkout integration/hostinger-backend

# 3. Pull the backend folder ONLY from the refactoring branch
# This updates all files in backend/ to match the refactoring branch.
# IMPORTANT: Since 'backend/.env' does not exist in the refactoring branch,
# git will NOT delete the existing 'backend/.env' on the Hostinger branch.
git checkout refactoring/17_12_25 -- backend/

# 4. Verify the critical configuration file is still there
ls -l backend/.env
```

---

## CRITICAL: Verification Before Push

**NEVER push to integration/hostinger-backend without completing ALL verification steps below.**

### Step V1: Syntax Verification (No Import Errors)

```bash
# Run main.py to check for syntax/import errors
# This should start the backend WITHOUT starting the frontend
# Press Ctrl+C after confirming no errors

cd /Users/nico/PycharmProjects/OpenEvent-AI
PYTHONDONTWRITEBYTECODE=1 python3 -c "from backend.main import app; print('✅ Syntax OK: No import errors')"
```

**Expected output:** `✅ Syntax OK: No import errors`
**If errors:** Fix them before proceeding. Do NOT push broken code.

### Step V2: API Endpoint Verification

Start the backend temporarily and test critical endpoints:

```bash
# Start backend in background
PYTHONDONTWRITEBYTECODE=1 uvicorn backend.main:app --port 8765 &
BACKEND_PID=$!
sleep 3

# Test health/root endpoint
echo "Testing root endpoint..."
curl -s http://localhost:8765/ | head -20

# Test conversation endpoint structure
echo "Testing /api/start-conversation..."
curl -s -X POST http://localhost:8765/api/start-conversation \
  -H "Content-Type: application/json" \
  -d '{"email_body": "Test", "from_email": "test@test.com", "from_name": "Test", "subject": "Test"}' | head -50

# Test pending tasks endpoint
echo "Testing /api/tasks/pending..."
curl -s http://localhost:8765/api/tasks/pending | head -20

# Kill test backend
kill $BACKEND_PID 2>/dev/null
```

**Expected:** All endpoints return JSON responses (not 500 errors or HTML error pages).

### Step V3: Verify .env Preserved

```bash
# Confirm .env still exists and has content
ls -la backend/.env
cat backend/.env | head -5  # Should show config, NOT be empty
```

---

## Commit and Push (Only After Verification Passes)

```bash
# 5. Stage and Commit the changes
git add backend/
git commit -m "feat(backend): sync backend changes from refactoring branch

Synced from: refactoring/17_12_25
Verification:
- Syntax check passed (no import errors)
- API endpoints tested (start-conversation, tasks/pending)
- .env configuration preserved
"

# 6. Push to Hostinger
git push origin integration/hostinger-backend

# 7. Return to your working branch
git checkout refactoring/17_12_25
```

---

## Why this is safe
- **`main.py`**: The file will be completely replaced by the new version. This is correct because the entire architecture has changed (endpoints moved to `backend/api/routes/`). The old `main.py` is incompatible with the new folder structure.
- **`backend/.env`**: This file is tracked on `integration/hostinger-backend` but **untracked/missing** on `refactoring/17_12_25`. When you run `git checkout refactoring... -- backend/`, Git only updates files that exist in the source. It does **not** delete files in the destination that are missing in the source (unlike a full branch merge). Thus, your API keys and secrets remain safe.
- **Host/Port Config**: The new `main.py` relies on standard `uvicorn` execution. Hostinger likely runs the app via a command like `uvicorn backend.main:app --host 0.0.0.0`, which overrides any internal code settings anyway.

## Troubleshooting
If you encounter a "conflict" or if `backend/.env` is accidentally deleted (unlikely):
1.  **Restore .env**: `git checkout HEAD -- backend/.env` (brings it back from the last Hostinger commit).
2.  **Verify**: Check the file content before pushing.

---

## Checklist Summary

Before every push to `integration/hostinger-backend`:

- [ ] All tests pass on source branch (refactoring/17_12_25)
- [ ] Syntax verification passed (`from backend.main import app` works)
- [ ] API endpoints return valid JSON (not errors)
- [ ] `backend/.env` still exists and has content
- [ ] Commit message documents what was synced and verified
