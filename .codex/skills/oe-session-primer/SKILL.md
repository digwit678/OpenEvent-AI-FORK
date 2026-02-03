---
name: oe-session-primer
description: Low-cost session context refresh. Reads /tmp primer if available; otherwise summarizes recent git activity and the most relevant docs without touching the working tree.
---

# oe-session-primer

## Goal

Get “what changed + what to watch” in under ~2 minutes without running tests, installs, servers, or modifying repo files.

## Steps

1. Prefer the automation output:
   - Read `docs/daily_scrum/session_primer.md` (if present).

2. If missing/stale, build a quick local primer:
   - Recent changes: `git log --since="72 hours ago" --name-only --oneline`
   - Skim (only if relevant/changed): `DEV_CHANGELOG.md`, `docs/guides/TEAM_GUIDE.md`, `TO_DO_NEXT_SESS.md`

3. Output (keep it short):
   - 5–10 bullets: changes, risks (routing/detection/workflow/site-visit/billing/HIL/fallback), and 1–3 suggested quick checks.

## Hard rules

- Do not modify the working tree.
- Do not run formatters, installs, servers, or test suites unless explicitly requested.
