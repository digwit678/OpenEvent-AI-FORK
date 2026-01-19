# Plan: Deploy Backend to Production (Main Branch)

**Objective:** Deploy backend changes from `development-branch` to `main` branch for production deployment.

## CRITICAL: Backend-Only Deployment

**⚠️ NEVER push frontend files (`atelier-ai-frontend/`) to main!**

- Frontend is deployed separately via Vercel/Lovable
- Main branch should contain ONLY backend code
- Always verify no frontend files are included before pushing

---

## Prerequisites

1. All changes committed and pushed to `development-branch`
2. Tests pass on development-branch
3. Workspace is clean (stash local dev files if needed)

---

## Step-by-Step Deployment Process

### Step 1: Prepare and Stash

```bash
# Stash any local uncommitted changes
git stash push -m "Local changes before main merge"

# Move any conflicting untracked files
mv conftest.py conftest.py.dev-backup 2>/dev/null || true
```

### Step 2: Checkout Main and Merge

```bash
# Switch to main and update
git checkout main
git pull origin main

# Merge development-branch (no commit yet to resolve conflicts)
git merge development-branch --no-commit
```

### Step 3: Resolve Conflicts

**Frontend files (modify/delete conflicts):**
```bash
# Delete frontend files - they should NOT be on main
git rm -f atelier-ai-frontend/app/components/debug/__tests__/*.tsx 2>/dev/null || true
git rm -f atelier-ai-frontend/app/components/mail/__tests__/*.tsx 2>/dev/null || true
git rm -f atelier-ai-frontend/package.json 2>/dev/null || true
# Remove any other frontend files that show as conflicts
git rm -rf atelier-ai-frontend/ 2>/dev/null || true
```

**tests/conftest.py (content conflict):**
```bash
# Keep main's version (uses pathlib, cleaner)
git checkout --ours tests/conftest.py
git add tests/conftest.py
```

**Other conflicts:** Review case-by-case. Generally:
- Keep main's test folder structure (tests/test_detection/, etc.)
- Accept development-branch's workflow handler changes

### Step 4: Verify Syntax

```bash
# Check Python syntax compiles
python3 -m py_compile main.py
python3 -m py_compile workflow_email.py
python3 -m py_compile workflows/steps/step1_intake/trigger/step1_handler.py

# If environment available, do full import check:
# python3 -c "from main import app; print('✅ OK')"
```

### Step 5: Commit and Push

```bash
# Check status - no conflicts should remain
git status | grep -E "both modified|Unmerged" || echo "✅ No conflicts"

# Commit the merge
git commit -m "Merge development-branch into main

Backend workflow improvements merged.
Frontend files excluded (deployed separately via Vercel).

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"

# Push to main
git push origin main
```

### Step 6: Return to Development

```bash
# Go back to development branch
git checkout development-branch

# Restore conftest.py if moved
mv conftest.py.dev-backup conftest.py 2>/dev/null || true

# Restore stashed changes
git stash pop
```

---

## Common Conflict Resolutions

| Conflict Type | Files | Resolution |
|--------------|-------|------------|
| modify/delete | `atelier-ai-frontend/*` | Delete (keep main's deletion) |
| content | `tests/conftest.py` | Keep main's version (pathlib) |
| rename | `tests/detection/` → `tests/test_detection/` | Accept main's structure |
| modify | Backend workflow files | Accept development-branch changes |

---

## Verification Checklist

Before every push to main:

- [ ] All tests pass on development-branch
- [ ] No frontend files in merge (`git status | grep atelier` returns empty)
- [ ] Syntax check passes (`python3 -m py_compile main.py`)
- [ ] No unresolved conflicts (`git status | grep Unmerged` returns empty)
- [ ] Commit message describes what was merged

After push:

- [ ] Verify deployment succeeds
- [ ] Test health endpoint if available

---

## Branch Structure

| Branch | Purpose | Contains |
|--------|---------|----------|
| `main` | Production | Backend only (flat structure) |
| `development-branch` | Development | Backend + Frontend |

---

## Troubleshooting

**"Untracked working tree files would be overwritten"**
```bash
mv conftest.py conftest.py.backup
# Then retry checkout/merge
```

**Frontend files accidentally pushed to main:**
```bash
git checkout main
git rm -rf atelier-ai-frontend/
git commit -m "chore: remove frontend from main"
git push origin main
```

**Merge conflict in binary/generated files:**
```bash
# Accept development-branch version
git checkout --theirs path/to/file
git add path/to/file
```

---

## Related Files

- Skill: `.claude/skills/oe-release-readiness/SKILL.md`
- Deploy docs: `deploy/README.md`
- CI workflow: `.github/workflows/workflow-tests.yml`
