# Open TODOs — Post Refactoring (Workflow-First)

**Date:** 2025-12-28  
**Goal:** Identify remaining open TODOs/issues referenced in markdown docs after the refactoring work, prioritized to make the **workflow (Steps 1–7) flawless** before moving to MVP integration work (Supabase/frontend/security).

This list was compiled by scanning repo markdown for: `TODO`, `TBD`, `FIXME`, unchecked checklists (`[ ]`), and explicit “Open/Investigating/FAIL” markers.

**Verification pass (2025-12-28):** Ran targeted `pytest` subsets and local `process_msg` repros (no code changes) to remove items that no longer reproduce.

---

## P0 — Workflow correctness blockers (fix first)

- Detours can still yield an empty workflow reply (no drafts returned), which triggers `empty_workflow_reply` fallback in API routes — `backend/api/routes/messages.py#L521`, `tests/specs/dag/test_change_integration_e2e.py` (entire file).
  - Verified repro (local): requirements change after reaching Step 3 can return `draft_messages=[]` with `action=structural_change_detour` (would surface as fallback via `/api/send-message`).
- Billing capture intermittent when driven through the frontend UI (accept → billing → deposit → HIL stuck) — `docs/guides/TEAM_GUIDE.md` (“Frontend Billing Capture Intermittent Failure (Investigating - 2025-12-23)”).

---

## P0.5 — Make core workflow tests green (treat FAIL as work items)
- run remaining md frontend pytests for q and as and smart shortcuts
- Verified failing suites (2025-12-28):
  - Q&A multi-turn freshness + weekday follow-up behavior — `tests/specs/date/test_general_room_qna_multiturn.py` (entire file).
  - Step 3 per-room date alternatives for vague ranges — `tests/specs/room/test_per_room_dates_vague_range.py` (entire file).
  - Change propagation / detour detection correctness — `tests/specs/dag/test_change_propagation.py` (entire file), `tests/specs/dag/test_change_scenarios_e2e.py` (entire file), `tests/specs/dag/test_change_integration_e2e.py` (entire file).
  - Hybrid queries (date gate + products/Q&A interactions) — `tests/specs/ux/test_hybrid_queries_and_room_dates.py` (entire file).
  - Q&A verbalizer/general reply expectations — `tests/workflows/qna/test_verbalizer.py` (entire file), `tests/workflows/qna/test_general_reply.py` (entire file).
  - Intake follow-up room choice routing — `tests/workflows/intake/test_room_choice_followup.py` (entire file).
  - Relative confirmation window edge case — `tests/workflows/date/test_confirmation_window_recovery.py` (entire file).
  - Offer product operations correctness — `tests/workflows/test_offer_product_operations.py` (entire file).
  - YAML flow spec runner expectations (multiple failing flows) — `tests/flows/test_flow_specs.py` (entire file).
- `tests/TEST_INVENTORY.md` is partially stale (example: `tests/specs/date/test_general_room_qna_flow.py` now passes; it also references missing paths like `tests/workflows/test_change_integration_e2e.py`). Refresh after failures are triaged.

---

## P1 — Validation gaps (still workflow-related, but not confirmed broken)

- “Tests NOT Yet Verified” checklist (Q&A coverage, shortcuts, and edge cases) — `docs/plans/active/TODO_NEXT_SESSION.md` (“Tests NOT Yet Verified”).
- Planned test coverage gaps (low-confidence escalation, quoted confirmation, buffer violations, calendar conflicts, billing validation) — `tests/TEST_REORG_PLAN.md` (“Test Coverage Goals (Steps 1-4 Focus)”).
- Playwright E2E spec checklist items are not all marked complete (treat these as “needs rerun + update status”, and implement missing automation if desired) — `tests/playwright/e2e/` (multiple `*.md` files; see checklists in each file).
- Date drift/corruption report in older Playwright notes does not reproduce in current stub runs; re-run Playwright to confirm and update status — `tests/playwright/e2e/04_core_step_gating/test_room_before_date.md` (entire file).
- Date mismatch “Feb 7 becomes Feb 20” does not reproduce for explicit confirmation in stub runs; keep as a watch item and re-validate in real UI/OpenAI mode — `docs/guides/TEAM_GUIDE.md` (“Date Mismatch: Feb 7 becomes Feb 20 (Open - Investigating)”).
- Mandatory time-slot booking (event + site visit) with manager-defined ranges — `docs/plans/active/time_slot_booking_plan.md`, `docs/plans/active/time_slot_booking_implementation_plan.md`.
- `docs/internal/backend/BACKEND_CODE_REVIEW_DEC_2025.md` “Immediate Action Items” contains stale checkboxes (example: Step 3 `request` NameError is already guarded); close or update this checklist after triage — `docs/internal/backend/BACKEND_CODE_REVIEW_DEC_2025.md` (entire file).
- Bundle the “add-ons/catering” question into the room-choice message (and accept combined replies: room + catering in one turn). Keep details in info pages; list only menu category names in chat — `docs/guides/step4_step5_requirements.md` (entire file), `DEV_CHANGELOG.md:3242`, `docs/plans/completed/JUNIOR_DEV_FOLLOW_UP.md` (entire file).

---

## P2 — MVP integration (Supabase + frontend/email wiring) (after workflow is stable)

- Supabase schema + credentials still “waiting” and integration open questions (approval triggers, email ingestion, realtime updates) — `docs/integration/frontend_and_database/status/INTEGRATION_STATUS.md` (“Part B”, “Part D”, and “Open Questions (Awaiting Co-Founder Response)”).
- Manager decisions needed for room reservation semantics, conflict handling, and UI approval flow — `docs/integration/frontend_and_database/guides/MANAGER_INTEGRATION_GUIDE.md` (Part 1 UX Decisions; multiple unchecked choices).
- Email workflow integration specification to validate against final decisions — `docs/integration/frontend_and_database/specs/EMAIL_WORKFLOW_INTEGRATION_REQUIREMENTS.md` (entire file).

---

## P3 — MVP security checklist (after workflow is stable, before production)

- Backend security MVP blockers and checklist items — `docs/integration/frontend_and_database/security/SECURITY_CHECKLIST_BACKEND.md` (entire file).
- Frontend + Supabase security MVP blockers and checklist items (RLS/login/API key handling) — `docs/integration/frontend_and_database/security/SECURITY_CHECKLIST_FRONTEND_SUPABASE.md` (entire file).
- Backend security TODO snippet (rate limiting, restrictive CORS, leakage review) — `docs/integration/frontend_and_database/status/INTEGRATION_STATUS.md` (“Backend Security TODO (Before Production)”).

---

## P4 — Post-MVP / longer-horizon plans and open decisions

- Open decisions around deposits and production payment verification — `docs/plans/OPEN_DECISIONS.md` (DECISION-001 and DECISION-003).
- Gemini dual-provider migration plan (unchecked implementation checklist) — `docs/plans/completed/MIGRATION_TO_GEMINI_STRATEGY.md` (Phase 1–3 checklists).
- Multi-tenant expansion plan (unchecked implementation checklist) — `docs/plans/active/MULTI_TENANT_EXPANSION_PLAN.md` (“Implementation Checklist”).
- Multi-variable Q&A plan / hybrid detection work (treat as future capability unless it is currently breaking workflow) — `docs/plans/active/MULTI_VARIABLE_QNA_PLAN.md` (entire file; see “Open Questions” section).
- On-demand site visit scheduling (LLM-only trigger + confirm gate) — `docs/plans/active/site_visit_on_demand_plan.md`.
- Test pages / Q&A shortcut follow-ups (verbalizer shortcut wiring, menus-to-rooms mapping, tests not run) — `DEV_CHANGELOG.md` (“Links, Test Pages, and Q&A Shortcuts” → “Open TODO / Testing”).
- Junior-dev follow-up checklist for test pages/links/Q&A shortcut behavior — `docs/plans/completed/JUNIOR_DEV_FOLLOW_UP.md` (“Testing Checklist”).
- Full-stack link/test-pages manual validation checklist (may be stale; re-run or archive) — `docs/plans/completed/DONE__JUNIOR_DEV_LINKS_IMPLEMENTATION_GUIDE.md` (entire file).
- Offer composition similarity threshold needs tuning/configurability — `docs/guides/step4_step5_requirements.md` (“Step 4 — Offer Composition” TODO notes).
- Gemini Flash “smart extraction” toggle to reduce regex brittleness and allow fast provider switching (OpenAI ↔ Gemini ↔ Hybrid) via profiles — `docs/plans/completed/MIGRATION_TO_GEMINI_STRATEGY.md` (entire file).
