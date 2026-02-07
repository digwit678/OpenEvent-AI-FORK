---
name: oe-docs-updates
description: Use after any bug fix/regression discovery, behavior/UX change, or workflow/routing/detection tweak (site-visit, billing, HIL, Q&A, confirmations). Keeps “living docs” in sync by updating TEAM_GUIDE.md, DEV_CHANGELOG.md, new_features.md, and TO_DO_NEXT_SESS.md with symptom keywords + test pointers.
---

# oe-docs-updates

## Workflow (keep entries small + actionable)

1. **If you fixed a bug**
   - Update `docs/guides/TEAM_GUIDE.md`:
     - Find the matching bug entry (search by keywords).
     - Mark status as fixed (or add “Fixed” note).
     - Add a link/reference to the regression test that now covers it (prefer `backend/tests/regression/test_team_guide_bugs.py` or a specs test).
   - Update `DEV_CHANGELOG.md`:
     - Add a short entry under today’s date: what changed + which tests verify it.

2. **If you discovered a bug but didn’t fix it**
   - Update `docs/guides/TEAM_GUIDE.md`:
     - Add it under the appropriate “Known Issues / Bugs” section.
     - Include: symptom, likely trigger, suspected module(s), minimal repro hint, and a suggested test file location.
   - Update `TO_DO_NEXT_SESS.md`:
     - Add a single-line task with priority and where to start (file path + test to write/run).

3. **If you added a feature or changed UX/behavior**
   - Update `DEV_CHANGELOG.md`:
     - Add: new behavior + migration/compat note (if any) + tests.
   - If it’s an idea that you are intentionally not implementing now:
     - Write it to `new_features.md` instead (see below).

4. **If you found a “future idea” while debugging**
   - Add it to `new_features.md`:
     - Keep it as a small ticket: context → current pain → proposed solution → files likely touched → priority.
     - Do not mix in a partial implementation here.

## Style rules (important for debugging agents)

- Prefer **searchable keywords** in headings and bullets (“billing capture”, “site visit”, “detour”, “HIL”, “smart shortcuts”).
- Always include **one concrete pointer**: failing test name, script path, or function/module.
- Avoid long narratives. Target: ≤10 lines per doc update.
