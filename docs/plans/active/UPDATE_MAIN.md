# Plan: Sync Backend Changes from Development to Main

**Objective:** Update the `backend/` (and root-level) code on the `main` branch (Vercel production) with the latest changes from `development-branch`.
**Context:** The project structure has moved to a flat root layout (e.g., `main.py` is at root, not `backend/main.py`).

## Prerequisites
- You are on `development-branch` with all changes committed
- All tests pass on development-branch
- Workspace is clean (`git status` shows no uncommitted changes)

## What Gets Synced

Everything that constitutes the "Backend" logic, now located at root:

| Root Files | Root Folders |
|------------|--------------|
| `main.py` | `adapters/`, `agents/`, `api/` |
| `workflow_email.py` | `config/`, `configs/`, `core/` |
| `config.py` | `data/`, `debug/`, `detection/` |
| `requirements.txt` | `domain/`, `llm/`, `services/` |
| `vercel.json` | `tests/`, `utils/`, `ux/` |
| | `workflow/`, `workflows/` |
| | `legacy/` (if needed) |

**Excluded:**
- `atelier-ai-frontend/` (Frontend is separate)
- `.dev/`, `.git/`, `.idea/`, `.venv/`
- Local database files (`events_*.json`)

## Execution Steps

### Step 0: Pre-Flight Check (CRITICAL)

**NEVER proceed to sync without completing this pre-flight check.**

```bash
# 1. Check for uncommitted changes
git status

# 2. Check essential root paths are tracked:
ls -la main.py workflow_email.py
ls -la workflows/ api/ domain/
```

**If any files are uncommitted:**
```bash
git add -A
git commit -m "chore: commit all pending changes before main sync"
git push origin development-branch
```

---


### Step 1: Verify Current Branch

```bash
git status
git branch --show-current  # Should show: development-branch
```

### Step 2: Switch to Main and Sync

```bash
# Switch to main
git checkout main
git pull origin main

# Sync ROOT FILES
git checkout development-branch -- main.py workflow_email.py config.py requirements.txt vercel.json

# Sync CORE FOLDERS (The new flat structure)
git checkout development-branch -- adapters/ agents/ api/ config/ configs/ core/ data/ debug/ detection/ domain/ llm/ services/ tests/ utils/ ux/ workflow/ workflows/ legacy/

# Sync legacy backend folder (if still needed for transition, otherwise empty)
git checkout development-branch -- backend/
```

### Step 3: Verify .env Preserved

```bash
# CRITICAL: Ensure production .env wasn't deleted (check both root and backend/ just in case)
ls -la .env
# If .env is missing, check if it was in backend/.env previously and move it if needed? 
# OR just restore it:
# git checkout HEAD -- .env
```

---


## CRITICAL: Verification Before Push

**NEVER push to main without completing ALL verification steps.**

### V1: Syntax Verification (No Import Errors)

```bash
# Run from ROOT
PYTHONDONTWRITEBYTECODE=1 python3 -c "from main import app; print('✅ Syntax OK: No import errors')"
```

**Expected output:** `✅ Syntax OK: No import errors`

### V2: Run Core Tests

```bash
# Run detection and regression tests
pytest tests/detection/ tests/regression/ -v --tb=short -q
```

### V2.5: Critical E2E Verification (The "Progressive Stability" Gate)

**Objective:** Ensure major functionality works in the browser.

```bash
# Run critical subset
npx playwright test \
  tests_root/playwright/e2e/03_critical_happy_path/test_full_flow_to_site_visit.spec.ts \
  tests_root/playwright/e2e/05_core_detours/test_date_change_from_step5.spec.ts \
  tests_root/playwright/e2e/06_core_shortcuts/test_date_plus_room_shortcut.spec.ts \
  tests_root/playwright/e2e/11_input_qna/test_static_qna.spec.ts
```

**Expected:** All selected specs pass.

### V3: API Endpoint Verification

```bash
# Start backend in background (from ROOT)
PYTHONDONTWRITEBYTECODE=1 uvicorn main:app --port 8765 &
BACKEND_PID=$!
sleep 3

# Test health
curl -s http://localhost:8765/api/workflow/health | jq .

# Kill test backend
kill $BACKEND_PID 2>/dev/null
```

---


## Commit and Push

```bash
# Stage ALL changes
git add .

# Commit
git commit -m "feat(backend): sync root-level backend structure from development-branch"

# Push
git push origin main

# Return
git checkout development-branch
```