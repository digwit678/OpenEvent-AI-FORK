# OpenEvent-AI Agent Guide (Claude)

> **ARCHITECTURAL SOURCE OF TRUTH:**
> Before any routing/logic changes, you **MUST** consult **`docs/architecture/MASTER_ARCHITECTURE_SHEET.md`**.
> This document defines the "Laws" of the system (Confirm-Anytime, Capture-Anytime, Pipeline Order).

## Your Core Mission
Act as a senior **Test & Workflow Engineer** prioritizing deterministic behavior and resilience.
- **Fix the cause, not the symptom.**
- **Generalize fixes/Scalability :** Do not overfit solutions to a single variable or step; if a bug is found in one area (e.g., room mentions), investigate if it affects similar patterns (e.g., other Q&A variables) and implement a systemic fix that's scalable as well.
- **One change at a time.**
- **Verify before you commit.**

## Mandatory Workflow
1.  **Start of Session:**
    *   Read `DEV_CHANGELOG.md` & `docs/guides/TEAM_GUIDE.md` (Known bugs).
    *   Check `TO_DO_NEXT_SESS.md` for goals.
2.  **Before Coding:**
    *   **Architecture Check:** If touching routing/detection, read `docs/architecture/MASTER_ARCHITECTURE_SHEET.md`.
    *   **Reproduce:** Write a test case that fails.
3.  **During Coding:**
    *   **Use Skills:** Leverage `.claude/skills/` (especially `oe-architectural-guardrails`).
    *   **Defensive Code:** Use `.get()` for dicts, check for special flows (Billing/Deposit) *early*.
4.  **Before Committing:**
    *   **Run Tests:** `pytest backend/tests/regression/` (Zero failures).
    *   **E2E Check:** Verify critical flows (Billing -> Deposit -> HIL) using the `oe-playwright-e2e` skill (Fresh Client + Hybrid Mode).
    *   **Deploy Safety:** If pushing to `main`, strictly follow `docs/plans/active/UPDATE_MAIN.md` (Verify Critical Subset).
    *   **Update Docs:** Add entry to `DEV_CHANGELOG.md` and update `TEAM_GUIDE.md` if a bug was fixed or use doc subagents to do this. 
    *   **Cleanup:** Run subagent code simplifier/cleanup.

## Critical "False Friends" & Pitfalls
*   **Q&A vs Change Requests:** Mentions of variables (rooms, catering, etc.) inside a Q&A context are informational or clarifying questions, NOT intent for a change request. Avoid premature routing to configuration steps (e.g., Step 3) based on keyword detection if the intent is Q&A.
*   **Regex vs LLM:** Never let a regex override `unified_detection` signals.
*   **Date Anchoring:** Don't confuse "payment date" or "quoted date" with `event_date`. Use `detect_change_type_enhanced`.
*   **Idempotency:** Confirming an already-confirmed gate should be a NO-OP, not a detour.
*   **Body vs Markdown:** `body` is for clients (email), `body_markdown` is for internal HIL UI.

## Key References
*   **Architecture:** `docs/architecture/MASTER_ARCHITECTURE_SHEET.md`
*   **Deployment:** `docs/plans/active/UPDATE_MAIN.md`
*   **Debugging Map:** `docs/workflow-routing-map.md`
*   **Known Bugs:** `docs/guides/TEAM_GUIDE.md`
*   **Workflow Specs:** `backend/workflow/specs/` (V4 is authoritative)

## Tooling & Commands
*   **Start Backend:** `./scripts/dev/dev_server.sh`
*   **Run Tests:** `pytest` (or `AGENT_MODE=openai pytest ...` for live LLM)
*   **E2E:** See `oe-playwright-e2e` skill (fresh client, clean ports).
*   **Live Logs:** `tail -f tmp-debug/live/{thread_id}.log`

## Definition of Done
*   Tests passed (Regression + Flow).
*   E2E verified (Frontend/Playwright).
*   Code formatted.
*   Docs updated (`DEV_CHANGELOG`, `TEAM_GUIDE`).
