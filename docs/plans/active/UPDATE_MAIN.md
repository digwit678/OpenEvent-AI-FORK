# Plan: Sync Backend Changes from Development to Main

> **Read this file completely before syncing.** Follow steps exactly.

**Objective:** Sync all **backend and docs** from `development-branch` to `main`, **excluding frontend** (`atelier-ai-frontend/`).

## Rules

1. **development-branch MUST NOT CHANGE** - only read from it
2. **main receives backend/docs ONLY** - no frontend files
3. **One-way sync**: development → main (never merge main into development)

## What Gets Synced

| Root Files | Root Folders |
|------------|--------------|
| `main.py`, `workflow_email.py` | `adapters/`, `agents/`, `api/` |
| `config.py`, `requirements.txt` | `backend/`, `config/`, `configs/`, `core/` |
| `vercel.json`, `pytest.ini` | `data/`, `debug/`, `detection/`, `docs/` |
| `CLAUDE.md`, `DEV_CHANGELOG.md` | `domain/`, `e2e-scenarios/`, `llm/` |
| `TO_DO_NEXT_SESS.md`, `new_features.md` | `scripts/`, `services/`, `tests/` |
| `.gitignore` | `tests_integration/`, `tests_root/` |
| | `utils/`, `ux/`, `workflow/`, `workflows/` |
| | `.claude/`, `.codex/`, `.playwright-mcp/` |

**Excluded (NEVER sync):**
- `atelier-ai-frontend/` (Frontend is separate)
- `.dev/`, `.git/`, `.idea/`, `.venv/`
- `events_team-*.json` (Runtime data, in .gitignore)

## Pre-Sync Checklist

```bash
# 1. Ensure you're on development-branch with clean state
git checkout development-branch
git status  # Should be clean (stash if needed)

# 2. Check for conflicts (should show nothing - 0 commits behind)
git fetch origin main
git log --oneline development-branch..main  # Should be EMPTY
```

**If development-branch..main shows commits:** STOP. Main has changes not in development. Investigate before proceeding.

---

## Sync Procedure

### Step 1: Stash and Switch

```bash
git stash push -m "temp: before main sync"
git checkout main
```

### Step 2: Selective Checkout (ALL backend directories)

```bash
git checkout development-branch -- \
  .claude/ \
  .codex/ \
  .playwright-mcp/ \
  adapters/ \
  agents/ \
  api/ \
  backend/ \
  config/ \
  configs/ \
  core/ \
  data/ \
  debug/ \
  detection/ \
  docs/ \
  domain/ \
  e2e-scenarios-playwright/ \
  llm/ \
  scripts/ \
  services/ \
  tests/ \
  tests_integration/ \
  tests_root/ \
  utils/ \
  ux/ \
  workflow/ \
  workflows/ \
  main.py \
  workflow_email.py \
  config.py \
  requirements.txt \
  vercel.json \
  pytest.ini \
  CLAUDE.md \
  DEV_CHANGELOG.md \
  TO_DO_NEXT_SESS.md \
  new_features.md \
  .gitignore
```

**Note:** Some directories may not exist. The checkout will error on non-existent paths - remove them from the command and continue.

### Step 3: Handle Deleted Files

If files were deleted in development-branch (e.g., `AGENT.md`), remove them from main:

```bash
# Check for files on main that don't exist in development
git diff --name-status main development-branch | grep "^D" | grep -v atelier

# Remove any that should be deleted
git rm <filename>  # for each deleted file
```

### Step 4: Verify No Frontend Files Staged

```bash
git diff --cached --name-only | grep -i atelier
# Should output NOTHING - if it shows files, unstage them:
# git reset HEAD atelier-ai-frontend/
```

---

## Verification Before Push (CRITICAL)

**NEVER push to main without these checks.**

### V1: Syntax Check

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -c "from main import app; print('✅ Syntax OK')"
```

### V2: Core Tests

```bash
pytest tests/detection/ tests/regression/ -v --tb=short -q
```

### V3: Final Diff Check

```bash
# Should only show frontend files as different
git diff --name-only main development-branch -- . ':!atelier-ai-frontend'
# Expected: empty or only runtime files (.dev/)
```

---

## Commit and Push

```bash
git commit -m "sync: backend and docs from development-branch (<source-commit-hash>)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

git push origin main
```

### Return to Development Branch

```bash
git checkout development-branch
git stash pop  # Restore working files
```

---

## Troubleshooting

### "Your local changes would be overwritten"
```bash
git stash push -m "temp: working files"
# Then continue with checkout
```

### Path doesn't exist error during checkout
Remove the non-existent path from the checkout command and continue. Not all directories exist in every project state.

### Files still different after sync
Check if they're runtime/temp files that should be in `.gitignore`:
```bash
git diff --name-only main development-branch | grep -v atelier
```

If files are tracked that shouldn't be:
```bash
git rm --cached <file>
git commit -m "chore: untrack runtime file (in .gitignore)"
```

### Frontend files accidentally staged
```bash
git reset HEAD atelier-ai-frontend/
# Then re-run verification step V4
```
