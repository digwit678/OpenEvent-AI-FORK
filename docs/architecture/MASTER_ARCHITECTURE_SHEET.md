# OpenEvent Master Architecture & Guardrails

> CRITICAL FOR AGENTS: Read this before changing routing, detection, or state.
> This doc is the fast map for debugging and safe edits.

## 0. Quick Map (Where to Start)

- Workflow entrypoint: `workflow_email.py` (`process_msg`)
- HTTP entry: `api/routes/messages.py` (`/api/send-message` -> `process_msg`)
- Pre-route pipeline: `workflows/runtime/pre_route.py`
- Router loop: `workflows/runtime/router.py`
- Step handlers:
  - Step 1: `workflows/steps/step1_intake/trigger/step1_handler.py`
  - Step 2: `workflows/steps/step2_date_confirmation/trigger/step2_handler.py`
  - Step 3: `workflows/steps/step3_room_availability/trigger/step3_handler.py`
  - Step 4: `workflows/steps/step4_offer/trigger/step4_handler.py`
  - Step 5: `workflows/steps/step5_negotiation/trigger/step5_handler.py`
  - Step 6: `workflows/steps/step6_transition`
  - Step 7: `workflows/steps/step7_confirmation/trigger/step7_handler.py`
- Detection: `detection/unified.py`, `detection/pre_filter.py`, `detection/intent/classifier.py`
- Site visits: `workflows/common/site_visit_handler.py`, `workflows/common/site_visit_state.py`
- State + DB: `workflows/common/types.py` (WorkflowState), `workflows/io/database.py`, `events_database.json`
- Config: `workflows/io/config_store.py`
- Verbalizer: `ux/universal_verbalizer.py`
- HIL tasks: `workflows/runtime/hil_tasks.py`
- Routing overview: `docs/workflow-routing-map.md`

## 1. Core Pipeline (Strict Order)

`workflow_email.py::process_msg()` orchestrates the pipeline.

1. **Load DB + State**: tenant-aware path -> `load_db()` -> `WorkflowState`.
2. **Step 1 Intake**: `step1_intake.process()` extracts `user_info`, updates `event_entry`.
   - Runs `detect_change_type_enhanced` and can trigger immediate detours via `route_change_on_updated_variable`.
3. **Pre-route pipeline**: `workflows/runtime/pre_route.py`
   - 0: pre-filter + unified detection (`run_unified_pre_filter`)
   - 0.6: out-of-context check (`check_out_of_context`)
   - 1: duplicate check (`check_duplicate_message`)
   - 2: post-intake halt
   - 3: guards (`evaluate_pre_route_guards`)
   - 4: smart shortcuts (`try_smart_shortcuts`)
   - 5: billing flow correction (`correct_billing_flow_step`)
4. **Router loop**: `workflows/runtime/router.py`
   - Dispatches current step (2-7).
   - **Site visit intercept**: `_check_site_visit_intercept` can handle requests at any step.
5. **Finalize + Persist**: `_finalize_output`, HIL task enqueue, empty-reply guard, DB flush.

## 2. Behavioral Invariants (Non-Negotiables)

1. **Confirm-anytime (Idempotent)**
   Redundant confirmation should not detour, regress, or drop other intents/QnA.

2. **Change-anytime (Anchored)**
   Detours require explicit change intent or bound targets. Never overwrite from unbound dates
   (quoted history, payment dates, etc).

3. **Capture-anytime**
   Billing/contact info must persist from any step. OOC checks must not drop it.

4. **Verbalizer truthfulness**
   Hard facts (dates, times, prices, units) must not be altered. Units are mandatory.

## 3. Key State Fields (Event Entry)

- Date: `event_entry.chosen_date`, `event_entry.date_confirmed`
- Room: `event_entry.locked_room_id`, `event_entry.room_eval_hash`
- Offer: `event_entry.offer_status`, `event_entry.offer_accepted`
- Billing: `event_entry.event_data["Billing Address"]`
- Deposit: `event_entry.deposit_state`, `event_entry.deposit_info`
- Site visit: `event_entry.site_visit_state`
- Thread: `event_entry.thread_state`
- Detection cache: `state.extras["unified_detection"]`, `state.extras["pre_filter"]`

## 4. High-Risk Bug Magnets

- Detection interference: check unified detection first; regex only as fallback.
- Date change confusion: always use `detect_change_type_enhanced`, avoid raw string compare.
- OOC drops: verify evidence checks (date/acceptance/counter) before dropping.
- Shortcuts + guards: re-evaluate when state changes (date/room locks).
- Site visit intercept: can hijack routing if state is active or intent is detected.
- HIL approvals: drafts must create tasks via `workflows/runtime/hil_tasks.py`.

## 5. Common Agent-Reported Bugs (Fast Checks)

- Simple confirmation at Step 5 gets OOC guidance: check `check_out_of_context` evidence gating in `workflows/runtime/pre_route.py`.
- Date change during billing ignored or overwritten: check billing capture in `step5_handler.py` and `correct_billing_flow_step` order in `workflows/runtime/pre_route.py`.
- Offer header wrong or pricing missing after room confirm: Step 3 should not halt; ensure Step 4 offer generation runs.
- HIL sends wrong body text: verify `add_draft_message` in `workflows/common/types.py` is not overwriting `body` with `body_markdown`.
- Site visit auto-selects date or misreads time as date: check site visit state transitions and slot parsing in `workflows/common/site_visit_handler.py`.
- Deposit UI appears too early or stale: verify frontend filters by `thread_id` and step; backend tasks should be scoped correctly.
- Quoted confirmation triggers QnA fallback: Step 2 should clear general QnA when a valid date/time is parsed.

## 6. Detection Hot Spots (Regex/Heuristic Fallbacks)

Use these as suspects when intent looks wrong or the LLM signal is ignored.

- Q&A keyword routing: `detection/intent/classifier.py` (`_detect_qna_types`), `detection/qna/general_qna.py`.
- Site visit keyword guard: `workflows/runtime/router.py` (explicit patterns).
- Step 7 classification keywords: `workflows/steps/step7_confirmation/trigger/classification.py`.
- Step 5 acceptance/rejection fallback: `workflows/steps/step5_negotiation/trigger/classification.py`.
- Date/time confirmation heuristics: `workflows/steps/step2_date_confirmation/trigger/step2_handler.py`.
- Change detection regex: `workflows/change_propagation.py`.
- Room shortcut heuristics: `workflows/steps/step1_intake/trigger/room_detection.py`.
- Pre-filter regex: `detection/pre_filter.py`.

Rules of thumb:
- Prefer `unified_detection` signals; treat regex as fallback only.
- Use word-boundary regex and strip quoted history/email/URLs before keyword scanning.
- Add regression tests for any new pattern or guard.

## 7. Debugging: "Where did it go?"

1. **OOC or Duplicate**: inspect `out_of_context_ignored` / `duplicate_message` actions.
2. **Step 1 Detour**: check `route_change_on_updated_variable` path.
3. **Guards**: did `evaluate_pre_route_guards` regress the step?
4. **Shortcuts**: did `try_smart_shortcuts` fast-forward state?
5. **Site visit intercept**: did `_check_site_visit_intercept` consume the message?
6. **Empty reply guard**: check `empty_reply_fallback` topic.

## 8. Related References

- `docs/workflow-routing-map.md`
- `docs/guides/TEAM_GUIDE.md`
- `docs/plans/active/site_visit_on_demand_plan.md`
- `docs/plans/active/time_slot_booking_plan.md`
- `docs/plans/active/time_slot_booking_implementation_plan.md`
