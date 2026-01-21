# Syncing Development Branch to Main

> **Read this file completely before syncing.** Follow steps exactly.

## Goal

Sync all **backend and docs** from `development-branch` to `main`, **excluding frontend** (`atelier-ai-frontend/`).

## Rules

1. **development-branch MUST NOT CHANGE** - only read from it
2. **main receives backend/docs ONLY** - no frontend files
3. **One-way sync**: development → main (never merge main into development)

## Pre-Sync Checklist

```bash
# 1. Ensure you're on development-branch with clean state
git checkout development-branch
git status  # Should be clean (stash if needed)

# 2. Check for conflicts (should show 0 behind)
git fetch origin main
git log --oneline development-branch..main  # Should be empty
```

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
  api/ \
  backend/ \
  configs/ \
  core/ \
  data/ \
  detection/ \
  docs/ \
  e2e-scenarios/ \
  scripts/ \
  services/ \
  tests/ \
  tests_integration/ \
  tests_root/ \
  tmp-cache/ \
  ux/ \
  utils/ \
  workflow/ \
  workflows/ \
  CLAUDE.md \
  DEV_CHANGELOG.md \
  TO_DO_NEXT_SESS.md \
  new_features.md \
  requirements.txt \
  pytest.ini \
  .gitignore \
  workflow_email.py
```

### Step 3: Handle Deleted Files

If any files were deleted in development-branch (like `AGENT.md`), remove them:

```bash
# Check for files that exist on main but not development-branch
git diff --name-only main development-branch | grep -v atelier-ai-frontend

# Remove any that should be deleted
git rm <filename>  # if applicable
```

### Step 4: Verify No Frontend Files

```bash
git diff --cached --name-only | grep -i atelier
# Should output NOTHING
```

### Step 5: Commit and Push

```bash
git commit -m "sync: backend and docs from development-branch (<commit-hash>)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

git push origin main
```

### Step 6: Return to Development Branch

```bash
git checkout development-branch
git stash pop  # Restore working files
```

## Files That Should NEVER Be Synced

| File/Directory | Reason |
|----------------|--------|
| `atelier-ai-frontend/` | Frontend (separate deployment) |
| `.dev/backend.pid` | Runtime process file |
| `events_team-*.json` | Runtime event data |
| `tmp-*/` | Temporary files |

These are in `.gitignore` and should not be tracked.

## Verification

After sync, verify no differences remain (except frontend and runtime files):

```bash
git diff --name-only main development-branch -- . ':!atelier-ai-frontend'
# Should only show: (nothing, or runtime files like .dev/)
```

## Troubleshooting

### "Your local changes would be overwritten"
```bash
git stash push -m "temp: working files"
# Then continue with checkout
```

### Missing directories in checkout
Some directories may not exist. The checkout command will error on non-existent paths - just remove them from the command and continue.

### Files still different after sync
Check if they're runtime/temp files that should be in `.gitignore`. If tracked accidentally:
```bash
git rm --cached <file>
git commit -m "chore: untrack runtime file"
```