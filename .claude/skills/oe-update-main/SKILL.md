---
name: oe-update-main
description: "Sync backend/docs from development-branch to main. MANDATORY skill when user says 'commit to main', 'sync to main', 'update main'. Re-reads docs/plans/active/UPDATE_MAIN.md every time. Prevents accidental frontend sync and ensures verification."
---

# oe-update-main

## STOP — You MUST Re-Read the Source Doc

**Before doing ANYTHING:**

```
Read file: docs/plans/active/UPDATE_MAIN.md
```

Do NOT proceed from memory. The instructions may have changed. Read it fresh.

---

## Critical Rules (Embedded for Safety)

1. **development-branch MUST NOT CHANGE** — only read from it
2. **main receives backend/docs ONLY** — NEVER sync `atelier-ai-frontend/`
3. **One-way sync**: development → main (never merge main into development)

## Pre-Sync Checklist (Run These Commands)

```bash
# 1. Verify you're on development-branch with clean state
git checkout development-branch
git status  # Must be clean

# 2. Check for conflicts - this MUST be empty
git fetch origin main
git log --oneline development-branch..main
```

**If `development-branch..main` shows ANY commits:** STOP. Do not proceed. Ask the user.

## Sync Procedure

After reading UPDATE_MAIN.md, follow its steps exactly:
1. Step 1: Stash and Switch
2. Step 2: Selective Checkout (use the exact command from the doc)
3. Step 3: Handle Deleted Files
4. Step 4: Verify No Frontend Files Staged

## Verification Before Push (MANDATORY)

**NEVER push to main without ALL of these:**

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
# Must show NOTHING or only frontend/runtime files
git diff --name-only main development-branch -- . ':!atelier-ai-frontend'
```

### V4: No Frontend Staged
```bash
git diff --cached --name-only | grep -i atelier
# Must output NOTHING
```

## Commit Format

```bash
git commit -m "sync: backend and docs from development-branch (<short-hash>)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

## After Push

```bash
git checkout development-branch
git stash pop  # If you stashed
```

---

## Common Mistakes This Skill Prevents

| Mistake | How This Skill Prevents It |
|---------|----------------------------|
| Syncing frontend accidentally | V4 check + explicit exclusion in rules |
| Pushing without tests | V1/V2 are mandatory before push |
| Working from stale memory | Forces re-read of UPDATE_MAIN.md |
| Modifying development-branch | Rule 1 embedded prominently |
| Merging main into development | Rule 3: one-way sync only |

---

## For Codex / Gemini Agents

If you are a Codex or Gemini agent executing this task:

1. **READ** `docs/plans/active/UPDATE_MAIN.md` at the start of every invocation
2. **FOLLOW** the exact commands from that file, not from memory
3. **VERIFY** all 4 verification steps before pushing
4. **STOP** and report if any verification fails