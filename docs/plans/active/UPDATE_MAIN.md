# Plan: Sync Backend Changes from Development to Main

**Objective:** Update the `backend/` folder on the `main` branch (Vercel production) with the latest changes from `development-branch`, ensuring:
1. Only backend code is synced (main is backend-only deployment)
2. Production configuration (`backend/.env`) is **preserved**
3. All changes are verified before push
4. **No push ever breaks production code or causes errors for customers.**

## Prerequisites
- You are on `development-branch` with all changes committed
- All tests pass on development-branch
- Workspace is clean (`git status` shows no uncommitted changes)

## What Gets Synced

| Include | Exclude |
|---------|---------|
| `backend/` (all backend code) | `atelier-ai-frontend/` (frontend removed from main) |
| `workflows/` (step handlers) | `.dev/` (local dev state) |
| `tests/` (test suites) | `events_*.json` (database state) |
| `detection/` (intent/entity) | `*.pid` files |
| `configs/` (config files) | |

## Execution Steps

### Step 0: Pre-Flight Check (CRITICAL)

**NEVER proceed to sync without completing this pre-flight check.** All essential files must be committed on development-branch first.

```bash
# 1. Check for uncommitted changes
git status

# 2. If there are uncommitted changes, commit them first:
git add -A
git status  # Review what will be committed

# 3. Look for essential uncommitted files in these directories:
git status --porcelain | grep -E "^\?\?" | grep -E "(backend|workflows|detection|tests|configs)/"

# 4. Specifically check these critical paths are NOT untracked:
ls -la backend/workflows/steps/  # Should show step handlers
ls -la detection/                 # Should show detection modules
ls -la workflows/                 # Should show workflow modules
```

**Checklist before proceeding:**
- [ ] `git status` shows clean working tree (no uncommitted changes)
- [ ] All files in `backend/`, `workflows/`, `detection/`, `tests/`, `configs/` are tracked
- [ ] No essential `.py` files are untracked (check `git status --porcelain | grep "\.py"`)
- [ ] Recent changes are committed with descriptive message

**If any files are uncommitted:**
```bash
# Commit all pending changes
git add -A
git commit -m "chore: commit all pending changes before main sync"
git push origin development-branch
```

**Why this matters:** If essential files are uncommitted on development-branch, they won't be synced to main, causing import errors or missing functionality in production.

---

### Step 1: Verify Current Branch

```bash
# Ensure you're on development-branch and it's clean
git status
git branch --show-current  # Should show: development-branch
```

### Step 2: Switch to Main and Sync Backend

```bash
# Switch to main
git checkout main

# Pull latest from remote
git pull origin main

# Sync backend folders from development-branch
git checkout development-branch -- backend/
git checkout development-branch -- workflows/
git checkout development-branch -- detection/
git checkout development-branch -- tests/
git checkout development-branch -- configs/

# Do NOT sync:
# - atelier-ai-frontend/ (removed from main - frontend not deployed)
# - .dev/ (local dev state)
# - events_*.json (database state)
```

### Step 3: Verify .env Preserved

```bash
# CRITICAL: Ensure production .env wasn't deleted
ls -la backend/.env
cat backend/.env | head -3  # Should show config values, not be empty
```

If `.env` was accidentally deleted:
```bash
git checkout HEAD -- backend/.env
```

---

## CRITICAL: Verification Before Push

**NEVER push to main (Vercel production) without completing ALL verification steps.**

### V1: Syntax Verification (No Import Errors)

```bash
cd /Users/nico/PycharmProjects/OpenEvent-AI
PYTHONDONTWRITEBYTECODE=1 python3 -c "from backend.main import app; print('✅ Syntax OK: No import errors')"
```

**Expected output:** `✅ Syntax OK: No import errors`
**If errors:** Fix them before proceeding. Do NOT push broken code.

### V2: Run Core Tests

```bash
# Run detection and regression tests (must all pass)
pytest tests/detection/ tests/regression/ -v --tb=short -q
```

### V3: API Endpoint Verification

Start the backend temporarily and test critical endpoints:

```bash
# Start backend in background
PYTHONDONTWRITEBYTECODE=1 uvicorn backend.main:app --port 8765 &
BACKEND_PID=$!
sleep 3

# Test health endpoint
echo "Testing /api/workflow/health..."
curl -s http://localhost:8765/api/workflow/health | jq .

# Test conversation endpoint structure
echo "Testing /api/start-conversation..."
curl -s -X POST http://localhost:8765/api/start-conversation \
  -H "Content-Type: application/json" \
  -d '{"email_body": "Test", "from_email": "test@test.com", "from_name": "Test", "subject": "Test"}' | jq . | head -20

# Test pending tasks endpoint
echo "Testing /api/tasks/pending..."
curl -s http://localhost:8765/api/tasks/pending | jq . | head -10

# Kill test backend
kill $BACKEND_PID 2>/dev/null
```

**Expected:** All endpoints return JSON responses (not 500 errors or HTML error pages).

---

## Commit and Push (Only After Verification Passes)

```bash
# Stage backend changes
git add backend/ workflows/ detection/ tests/ configs/

# Commit with verification note
git commit -m "feat(backend): sync backend changes from development-branch

Synced from: development-branch

Verification:
- Syntax check passed (no import errors)
- Core tests passed
- API endpoints tested
- .env configuration preserved
"

# Push to Vercel (main branch)
git push origin main

# Return to development branch
git checkout development-branch
```

---

## Known Conflicts with Main (as of 2026-01-13)

| File | Conflict Type | Resolution |
|------|---------------|------------|
| `atelier-ai-frontend/*` | Modify/Delete | Accept deletion (frontend removed from main) |
| `tests/detection/` paths | Reorganization | May need path adjustments |

**Note:** Frontend changes (e.g., deposit session filtering in `page.tsx`) don't apply to main since frontend was removed. Backend changes work independently.

---

## Why This Is Safe

- **Backend isolation:** Only backend folders are synced, not frontend
- **`.env` preservation:** Git checkout only updates files that exist in source; it doesn't delete files missing from source
- **Verification gates:** Syntax + tests + API checks catch issues before push
- **Rollback:** If something breaks, `git revert HEAD` on main immediately

---

## Checklist Summary

Before every push to `main` (Vercel production):

**Pre-Flight (Step 0):**
- [ ] `git status` shows clean working tree on development-branch
- [ ] All essential files are committed (no untracked .py files in backend/workflows/detection/tests/)
- [ ] Changes pushed to development-branch remote

**Verification (Steps V1-V3):**
- [ ] All tests pass on development-branch
- [ ] Syntax verification passed (`from backend.main import app` works)
- [ ] API endpoints return valid JSON (not errors)
- [ ] `backend/.env` still exists and has content
- [ ] Commit message documents what was synced and verified
- [ ] No frontend files accidentally synced

---

## Troubleshooting

**If .env is deleted:**
```bash
git checkout HEAD -- backend/.env
```

**If import errors occur:**
```bash
# Check for missing dependencies
pip install -r requirements.txt
# Check for circular imports
python3 -c "from backend.main import app"
```

**If tests fail on main but not development-branch:**
```bash
# May need to sync test fixtures
git checkout development-branch -- tests/fixtures/
```
