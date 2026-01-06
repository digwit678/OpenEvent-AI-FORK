# Workflow Generalization Review

Goal
- Make detours, QnA, shortcuts, and capture/verification rules work from any step.
- Avoid step-specific hardcoding that blocks new steps or requires repeated manual updates.
- Ensure captured gatekeeping variables persist and auto-verify when confirmed so clients never re-provide data.

Workflow Pipeline Map (what actually runs today)
- Intake: `backend/workflow_email.py` -> `process_msg()` runs Step1 intake, then pre-route, then routing loop.
- Pre-route pipeline: `backend/workflows/runtime/pre_route.py`
  - Unified pre-filter + LLM detection
  - Manager escalation
  - Out-of-context intent filter (can silently ignore)
  - Duplicate detection
  - Guards (step2-4 only)
  - Smart shortcuts
  - Billing step correction
- Routing loop: `backend/workflows/runtime/router.py`
  - Dispatches steps 2-7 only
  - Site-visit intercept runs at any step
- Step handlers: `backend/workflows/steps/step2..step7/*`
  - Each step has its own change detection, QnA logic, and detour rules
- Finalization + HIL tasks: `backend/workflows/runtime/hil_tasks.py`

Key Behavioral Invariants (based on your clarified rules)
- Confirm-anytime means: confirm/verify ONLY gates that are currently pending/unverified. If a gate is already verified, “confirmation” must be a NO-OP (must not re-run Step2/3/4 logic, must not detour, must not emit HIL).
- Change-anytime means: if the user proposes a DIFFERENT value for a verified gate (date/room/participants/products/billing/etc), treat it as a change request (detour to the owning step) only when the message is clearly about changing the event (revision signal + bound target). Mentions of dates/rooms in unrelated contexts must not trigger detours.
- Capture-anytime means: any gate value can be extracted at any step, stored, and never lost. The user should never have to re-type a value they already provided earlier.
- Verify-without-retyping means: when the owning step needs a value and it already exists (captured or already stored in canonical fields), the step should (a) not ask for the raw value again, and ideally (b) auto-verify it unless there’s a conflict/ambiguity.
- Multi-signal messages must be processed holistically: a “reconfirm” token inside a message must not cause an early ignore that drops other actionable content (billing, change, questions, etc).

Findings With Impact, Benefit, And Solution (with concrete mistakes)

1) Out-of-context intent gating is hardcoded
Current problem
- Intent validity is controlled by INTENT_VALID_STEPS and ALWAYS_VALID_INTENTS, a static map in `pre_route.py`.
- New intents or steps require manual updates; otherwise intents are treated as valid everywhere or silently ignored.

Why it is a problem
- This is brittle as the workflow grows. A new step or intent can behave incorrectly without any explicit error.
- "Silent ignore" is risky when a user takes a valid action but the step map is not updated.

Impact
- New step-specific intents can be mishandled or ignored.
- More step additions mean more manual edits and higher regression risk.

Concrete mistakes you can hit
- Example (interference): At Step 5, date is already verified (so reconfirm should be NO-OP), but the client sends
  “Event date: 12.05. Billing address: …”. If unified detection returns `confirm_date`, `check_out_of_context()` can ignore
  the entire message at pre-route. Result: billing is never captured, and the workflow appears stuck even though the user
  did the right thing. This is a correctness bug caused by an early-return filter that doesn’t consider multi-intent content.
- Example (stuck state repair): Because of an inconsistent state (e.g., `chosen_date` exists but `date_confirmed=False` after a detour),
  the event is at Step 4/5. The client sends a clean confirmation with time (“Yes: 12.05, 14:00–16:00.”).
  If unified detection returns `confirm_date`, the pre-route out-of-context gate can silently ignore it, preventing the user from
  repairing the missing gate “from any step”.
- Example: You add a new step8 intent `confirm_contract`. If you forget to add it to INTENT_VALID_STEPS,
  the system treats it as valid anywhere. Step3 will try to handle it as normal text and likely fall into QnA or noop,
  meaning the contract confirmation is effectively ignored without a detour.
- Example: You do add `confirm_contract` to INTENT_VALID_STEPS but forget to include step8 in the list.
  At step8, messages are now "out of context" and silently ignored.

Benefit of fixing
- Step expansion becomes safer. Intent routing is data-driven and consistent across steps.
- Improves correctness for detours and shortcuts (intent-based routing stays aligned).

How to solve (general solution)
- Move intent context rules into a shared metadata registry (IntentSpec), keyed by intent label.
- Use gate state (verified/pending) + detection signals (`is_change_request`, entities, step anchor) to decide whether an intent is actionable.
- Importantly: avoid “ignore the whole message” early returns. If one sub-intent is out-of-context or a reconfirm NO-OP, continue processing
  the rest of the message (capture billing, answer QnA, detect true changes).
- Default behavior should be explicit (for example, unknown intent -> allow, but log).

2) Gatekeeper state is hardcoded to step2/step3/step4/step7
Current problem
- Gatekeeper defaults and refresh logic only track steps 2, 3, 4, and 7.
- Step5/step6 (and any future steps) do not get gate status, explain info, or telemetry.

Why it is a problem
- Gatekeeping variables are central to detours, shortcuts, and verification.
- Hardcoded gates prevent general rules from working across all steps.

Impact
- New steps or variables are not tracked.
- QnA cannot surface missing info for new steps.
- Detours and shortcuts cannot reason over missing gates if they are not represented.

Concrete mistakes you can hit
- Example: Step6 blocks on `deposit_state` in `step6_handler.py`, but `gatekeeper_passed` never tracks deposit status.
  Any generic "what's missing?" logic driven by gatekeeper will never mention deposits, even if required.
- Example: Step7's confirmation gate uses `event_data["Company"]` and `event_data["Billing Address"]`.
  If these are captured out-of-order (for example in Step2), they are not reflected in gatekeeper state,
  so you can still get "billing.address missing" even though the data exists.

Benefit of fixing
- A single gate model can power detours, shortcuts, QnA, and auto-verification for all steps.
- Eliminates repeated edits across multiple modules.

How to solve (general solution)
- Define a GateSpec registry (data-driven) for each gatekeeping variable:
  - id, owning_step, dependencies, compute_value(state), verify_rules, prompt_hints
- Compute `gatekeeper_passed` by iterating GateSpec, not by step number.
- Use the same GateSpec for missing-fields, verification prompts, and detour routing.

3) HIL task routing is limited to steps 2-5
Current problem
- HIL tasks are only created for steps 2-5 and mapped to fixed action types.
- Any new step that needs approval is silently ignored.

Why it is a problem
- Approval workflows should be a capability, not a fixed whitelist.
- General rules (like "draft requires approval") do not work for new steps.

Impact
- HIL approvals for new steps will never be created.
- Requires a hardcoded update every time a new approval step is added.

Concrete mistakes you can hit
- Step 6 already creates drafts with `requires_approval: True` (`transition_clarification`) but
  `enqueue_hil_tasks()` ignores step 6, so no approval task is created. That draft never reaches HIL.
- Step 7 creates approval-required drafts (`confirmation_deposit_pending`, `confirmation_final`),
  but HIL task creation still skips step 7. These approvals never surface.

Benefit of fixing
- Any step can create approvals without extra plumbing.
- More consistent HIL handling and fewer missed approvals.

How to solve (general solution)
- Move approval routing into StepSpec metadata:
  - approval_enabled, approval_queue, approval_action_type
- Generate action type dynamically (for example `step_{id}_approval`) if not specified.
- Remove the step whitelist and rely on draft metadata + StepSpec.

4) QnA missing-fields logic is step-specific (steps 2-4)
Current problem
- `_missing_fields` in QnA is hardcoded for steps 2-4 only.
- No generic path for other steps or new gate variables.

Why it is a problem
- QnA answers cannot guide users on missing data for new steps.
- The logic diverges from gatekeeping state, so prompts can be inconsistent.

Impact
- QnA becomes stale as the workflow expands.
- Users may be asked for information they already provided.

Concrete mistakes you can hit
- Example: At Step 7, user asks "What else do you need from us?" The QnA missing-fields helper
  never mentions deposit or billing because it only knows steps 2-4. Response can be misleading.
- Example: At Step 6, user asks any QnA. Step6 has no QnA handling at all; it only emits blockers.
  The user's question is ignored and they get a transition-blocked response.

Benefit of fixing
- QnA and gatekeeping stay aligned.
- New steps automatically get accurate missing-field prompts.

How to solve (general solution)
- Build missing-fields from the GateSpec registry and current gate states.
- Expose missing fields based on "verified = false" and "captured = false".

5) Step name mapping is duplicated across modules
Current problem
- Step name maps exist in multiple files (trace, types, step handlers).
- Adding a new step requires updating several scattered maps.

Why it is a problem
- Inconsistent naming makes logs, traces, and UI confusing.
- Easy to forget one map and introduce drift.

Impact
- Debugging becomes noisy and unreliable.
- More manual work on every step change.

Concrete mistakes you can hit
- Example: You add Step 8 but only update the map in `workflows/common/types.py`.
  Trace output still labels it "intake", and debug tooling uses the wrong step name, which hides issues.

Benefit of fixing
- One authoritative step registry reduces error and maintenance cost.

How to solve (general solution)
- Centralize step names in a WorkflowStep enum or StepRegistry.
- Use helper functions for name lookup everywhere.

6) Empty-reply fallback is step-specific to steps 3-5
Current problem
- Fallback copy is hardcoded for steps 3-5; other steps get generic text.

Why it is a problem
- New steps do not get tailored fallback responses without manual edits.

Impact
- Lower UX quality for new steps.

Concrete mistakes you can hit
- Example: New step8 returns no draft because of a missing branch.
  The fallback is generic and does not tell the client what is happening in step8.

Benefit of fixing
- Consistent fallback behavior for all steps.

How to solve (general solution)
- Use StepSpec fallback text or a universal verbalizer template keyed by step.
- Default fallback can be generated from step metadata.

General Architecture Proposal (aligned with your goals)

A) Central Step Registry
- StepSpec fields: id, name, owner_label, fallback_copy, approval_settings, qna_topics
- Used for:
  - Routing, tracing, HIL approvals, fallback copy, UI labels

B) GateSpec Registry (gatekeeping variables as data)
- GateSpec fields: id, owning_step, dependencies, compute(state), verification_rules
- State per gate: captured_value, verified, verified_at, source
- Used for:
  - Gatekeeper status
  - Missing-fields for QnA
  - Detour and shortcut routing
  - Automatic verification and skip logic

C) Capture And Verification Pipeline (global, step-agnostic)
- On every message:
  1) Detect and update any gate variables (capture) regardless of current step.
  2) If a captured variable is already verified, do not ask again.
  3) If confirmation detected and matches a gate variable awaiting verification, auto-verify.
  4) If multiple variables confirmed, verify all and re-evaluate next step.

D) General Detour Logic
- Detour destination derived from GateSpec.owning_step for any updated gate.
- If multiple gates change, jump to the earliest missing gate or the lowest owning_step.

E) General Shortcut Logic
- After capture/verification, compute next step from the registry:
  - Find the earliest step with missing or unverified gates.
  - If none missing, proceed to the next "normal" step.
- This allows users to provide multiple gates in one message without extra prompts.

Result
- Adding a new step becomes mostly data-only work:
  - Add StepSpec + GateSpec entries
  - No changes required in pre-route, QnA, HIL, or gatekeeper logic

Additional Non-Generic Hotspots That Break Your Rules

Detour logic is fragmented across steps (not one general rule)
- `change_propagation.py` is used by Steps 1-4, but Steps 5 and 7 each implement their own change detection.
- Step6 has no change detection at all.
- Concrete mistakes:
  - Client changes the date in Step6: Step6 ignores it and returns blockers, no detour.
  - Client changes "billing address" in Step7: `_detect_structural_change` ignores billing changes,
    so no detour or capture happens.

Shortcuts do not allow multi-gate confirmation in one message
- AtomicTurnPolicy only executes one verifiable intent (or date+room combo) and defers the rest.
- Concrete mistake:
  - Client says "Date 12/5, Room A, 40 people, add catering."
    The planner can execute date+room, but participants/catering are deferred and not verified in the same turn.
    This violates "confirm more than one gatekeeping variable any time."

Capture/verification is not global
- `capture_user_fields()` is only called in Step 2.
- `promote_fields()` is only called in Step 2.
- `verified` store exists but is not used elsewhere.
- `promote_billing_from_captured()` is never called.
- Concrete mistakes:
  - Client provides billing address in Step1 or Step3. It is not captured, so Step7 still asks again.
  - Client provides company + billing in Step2; it lands in `captured` but is never promoted to `event_data`,
    so Step7 gate still shows missing billing info.
  - Client provides start/end time in Step4; it is not captured for Step2 verification later.

Reconfirmation hazards (violates “no re-confirming”)
- Smart shortcuts can re-run date confirmation even when the date is already verified:
  - `parse_date_intent()` creates a `date_confirmation` intent whenever `user_info` contains `date/event_date`, without checking if
    the event already has `date_confirmed=True` or if the window matches the existing one.
  - `apply_date_confirmation()` calls Step2’s `_finalize_confirmation()`, which sets `current_step=3` and can trigger Step3 logic.
- Concrete mistake:
  - Event is at Step 5. Client replies with a short message, but the email body includes quoted history containing the original date/time.
    Entity extraction picks up the quoted date/time, shortcuts treat it as a fresh `date_confirmation`, and Step2 finalize runs again.
    Result: workflow jumps back to Step 3, and the user “reconfirmed” a date they were not supposed to reconfirm.
- Fix approach:
  - In shortcuts, treat `date_confirmation` as actionable only if date is not yet verified OR the window differs AND there is an explicit
    revision signal. If it’s the same window and already verified, treat as NO-OP (record telemetry and continue).

Quoted-text / forwarded-email interference (root cause for many false triggers)
- Many detectors run on the raw email body and may parse quoted history (previous dates, rooms, prices).
- Concrete mistakes:
  - A client replies “Thanks” but the quoted thread includes “14.02.2026”. Step5’s fallback date parsing sees a different date and detours
    to Step2 (“negotiation_changed_date”) even though the client did not request a change.
  - A deposit email includes a payment date; Step7 sees a date different from `chosen_date` and detours to Step2 (“confirmation_changed_date”).
- Fix approach:
  - Introduce a single “normalized message text” function used by ALL detectors/extractors (strip quoted history, signatures, forwarded headers).
  - Apply it before change detection, unified detection, and shortcut parsing.

Routing loop only knows steps 2-7
- Detours to Step1 are impossible because Step1 is not in the router.
- Example: Step3 capacity check explicitly says it cannot detour to Step1, so it halts instead.

Guards are step2-4 only
- `workflow/guards.py` enforces Step2/3/4 readiness, not Step5/6/7.
- Example: If you add a new gate variable owned by Step6, guards never force Step6,
  so "earliest missing gate" logic fails.

Implementation Checklist (concrete, minimal touchpoints)

1) Add canonical message normalization (prevents detector interference)
- Add a single helper like `normalize_incoming_text(subject, body) -> str` that:
  - Removes quoted history / forwarded headers / signatures (best-effort heuristics).
  - Produces BOTH `normalized_body` and `normalized_combined` (if you still need subject).
- Use it consistently in:
  - Change detection (Step1, Step5, Step7)
  - Unified detection input (pre-route)
  - Smart shortcuts parsing (pre-route)
  - Duplicate detection storage/comparison

2) Make “confirm” idempotent and gate-state-based (no reconfirm)
- Add a small gate-state check for each confirmable gate:
  - Date: `date_confirmed == True` AND same window hash -> confirm is NO-OP
  - Room: `locked_room_id` equals requested -> confirm is NO-OP
  - Participants: same value -> NO-OP
  - Billing: already complete -> NO-OP
- Where to enforce:
  - Smart shortcuts (highest priority): don’t generate/execute date_confirmation intent if already verified and unchanged.
  - Step handlers: if they receive a “confirm” for an already-verified gate, do not detour backwards.

3) Replace “out-of-context step map” with “actionability” checks (prevents early-drop bugs)
- Current behavior: a single detected intent can early-return “no response”.
- Replace with:
  - If intent is step-specific but the gate is already verified -> treat as NO-OP intent and continue processing other content.
  - If the gate is NOT verified -> allow detour/verification (even if current_step is later) OR at least don’t block the message.
  - Only “ignore” when the entire message is confidently a wrong-step action AND contains no other actionable signals (no changes, no billing, no QnA).

4) Make capture global (so users never retype)
- Call `capture_user_fields()` for every message (not only Step2).
  - Preferred place: immediately after Step1 intake + entity extraction and before guard/shortcuts, so everything downstream sees captured values.
- Decide promotion policy:
  - Conservative: promote captured->canonical only when owning gate is being verified now.
  - Aggressive (matches your goal): promote and mark verified automatically at owning step if no conflicts.
- Wire promotion helpers (billing is already implemented as `promote_billing_from_captured()` but unused).

5) Prevent cross-detector double-handling (consistent precedence)
- Enforce a single precedence order, ideally globally:
  1) Normalize text
  2) Capture values (no state transitions)
  3) Detect true changes (revision + target + value differs) -> detour
  4) Verify pending gates (can verify multiple) -> advance
  5) QnA (must not mutate gates)
  6) Step-specific handling
- This prevents cases where QnA detection hides a change, or out-of-context hides billing capture.

6) Add “safety tests” for interference regressions
- Minimal tests to add (high value):
  - Reconfirm-date at Step5 with same date/time does not change `current_step`.
  - Message with billing + repeated date at Step5 does not get dropped by out-of-context filtering.
  - Quoted history containing a different date does not trigger a detour when the user’s new text doesn’t request a change.

---

# Pre-launch Stress Test Log (no fixes applied yet)

Environment / prerequisites
- Real OpenAI key is present (`OPENAI_API_KEY` set).
- On macOS, missing `OPENAI_API_KEY` / `GOOGLE_API_KEY` can be auto-loaded from Keychain when the OpenAI/Gemini adapters are constructed.
  - Keychain services: `openevent-api-test-key` (OpenAI, account `$USER`) and `openevent-gemini-key` (Gemini).
  - Existing env vars still take precedence; set `OE_DISABLE_KEYCHAIN_ENV=1` to opt out.

Related: current routing overview (for debugging)
- `docs/workflow-routing-map.md`

## Automated tests run

1) Full suite
- Command: `pytest -q`
- Result: 2 failing tests (all other tests pass; plus expected xfails).
- Failures
  - `tests/e2e_v4/test_full_flow_stubbed.py::test_stubbed_flow_progression[room_status0]`
    - Expected: Step3 HIL approve path updates the event room
    - Actual: crashes with `ValueError: Event EVT-E2E not found` inside `update_event_room(db={'events': []}, ...)`
    - Impact: Any path that calls `update_event_room()` when the event is not present in `state.db["events"]` hard-crashes; error handling is not graceful.
    - Mitigation idea: ensure `state.db` always contains the working `event_entry` (single source of truth), or make update helpers accept and operate on the provided `event_entry` (and reconcile into db) instead of re-looking up by id and raising.
  - `tests/flows/test_flow_specs.py::test_flow_past_date`
    - Expected: past-date message triggers the past-date shortcut behavior defined in the flow spec
    - Actual: routes differently (assert mismatch in returned action/intent_detail/current_step)
    - Impact: dates in the past can derail the intended correction/shortcut flow; users may get stuck or receive an irrelevant response.
    - Mitigation idea: re-align the “past date” rule between flow specs and the current routing logic (single authoritative rule).

2) Pre-launch regression probes (xfail-only; no production code changes)
- File: `tests/specs/prelaunch/test_prelaunch_regressions.py`
- Command: `pytest -q tests/specs/prelaunch/test_prelaunch_regressions.py -rxX`
- Result: all tests currently XFAIL (they are “known-bad” behaviors we want to eliminate before launch).
- What these probes cover (each has a concrete reproduction + a “desired behavior” assertion):
  - Out-of-context ignore drops billing (multi-intent loss).
  - Out-of-context early-return skips persistence (Step1 updates not saved).
  - Step1 legacy “date change” fallback overwrites chosen_date from unrelated dates (deposit payment date, quoted thread).
  - Smart shortcuts can reconfirm an already-confirmed date and regress steps.
  - Step7 structural change detours on any extracted date (even deposit/payment dates).
  - Step6/7 drafts require approval but final payload has no `actions` and no HIL routing.
  - Gatekeeper ignores captured billing/company (forces re-typing).
  - Hybrid validation says OK even if Gemini key is missing; unified detection crashes instead of falling back.
  - Concurrency: two concurrent turns can lose updates (last-writer-wins).

## Real-key / runtime stress tests (OpenAI)

### A) Unified detection can classify “confirm date” even when the date is already confirmed (Step5), causing a global out-of-context drop
What I tested
- Command (OpenAI unified detection): `INTENT_PROVIDER=openai DETECTION_MODE=unified python3 -c ... run_unified_detection(...)`
- Message: `"We confirm the date. Billing address: ACME AG, Bahnhofstrasse 1, 8001 Zurich."`

Expected
- Because the date is already confirmed at Step5, “confirm_date” should be treated as NO-OP (not actionable) and the system should still capture billing.

Actual
- Unified detection returned:
  - intent: `confirm_date` (high confidence)
  - entities.billing_address extracted correctly
- In full workflow execution (`process_msg` with a seeded Step5 event), pre-route out-of-context handling triggers:
  - action: `out_of_context_ignored`
  - result: message is silently ignored and the billing address is not persisted at all
  - also: the message id is not tagged onto the event (`msgs` stays empty) because the out-of-context early return happens before persistence flush.
- Reproduced the same behavior in hybrid mode (Gemini intent/extraction + OpenAI verbalization) by exporting `GOOGLE_API_KEY` from Keychain.

Concrete “how this breaks production”
- Client sends one email with two things: reconfirmation + billing.
- The system ignores it because it sees “confirm date” as a step-2 action.
- Billing never gets stored → later Step7 will ask again and the client will feel the system is broken.

Mitigation ideas (no code changes applied yet)
- Replace static `INTENT_VALID_STEPS` with “actionability” rules:
  - confirm intent is actionable only if that gate is pending/unverified
  - if already verified, treat as NO-OP and continue processing the rest of the message (capture, QnA, etc.)
- Ensure every pre-route early return persists Step1 updates (or run out-of-context before Step1 mutation, or both).

### B) Deposit payment messages containing a date can overwrite the event date (catastrophic)
What I tested
- `process_msg` with a seeded Step7 event (chosen_date=12.05.2026, deposit required/requested), OpenAI extraction enabled.
- Message: `"We paid the deposit on 02.01.2026. Please confirm receipt."`

Expected
- The date `02.01.2026` is a payment date (or at least ambiguous) and should not be treated as an event date change without a revision signal + bound target.
- The workflow should stay in the confirmation/deposit lane and mark deposit as paid (or ask for proof).

Actual
- Step1 intake extracts `event_date=02.01.2026` and hits the legacy fallback:
  - “if extracted event_date differs from chosen_date → treat as date change”
- Result:
  - The event detours to Step2 and rewrites `chosen_date` to `02.01.2026`
  - The router then proceeds forward (Step2→Step3→Step4), effectively corrupting the booking details from a deposit email.
- Reproduced the same corruption in hybrid mode by running with `AGENT_MODE=gemini` and `GOOGLE_API_KEY` loaded from Keychain.

Concrete “how this breaks production”
- A client includes a payment date in their deposit email.
- The system silently changes the event date to the payment date, potentially sending wrong offers/availability checks and breaking the real booking.

Mitigation ideas
- Delete/disable the legacy “date change if date differs” fallback, or gate it behind the same dual-condition logic used by `detect_change_type_enhanced` (revision signal + bound target).
- Add a global “message normalization + segmentation” layer (strip quoted history; separate deposit/payment context from event-date context).
- Add step-aware intent anchoring: in Step7 deposit flows, treat extracted dates as payment dates unless an explicit event-date change phrase is present.

### C) Deposit paid without a date can work, but deposit schemas drift
What I tested
- Same seeded Step7 event, message: `"We paid the deposit. Please confirm receipt."`

Expected
- Deposit should be marked paid in a single canonical place and any downstream gate checks should observe it consistently.

Actual
- Step7 marks `deposit_state.status = "paid"` (legacy schema) but leaves `deposit_info.deposit_paid = False` (new schema).

Impact
- Any logic that keys off `deposit_info` may think the deposit is still missing even after it was “paid”.
- This can cause inconsistent new-event detection, blockers, or repeated deposit prompts.

Mitigation ideas
- Define a single canonical deposit schema and enforce bidirectional syncing during migration (or remove one).
- Add a “deposit gate” to the GateSpec/Gatekeeper model so it’s computed once, not duplicated.

### D) Concurrency stress: DB updates can be lost under concurrent turns
What I tested
- Two concurrent `process_msg` calls against the same DB file, forced to load the DB before either proceeds (barrier).

Expected
- Both messages should be reflected in the event (e.g., both msg_ids appear in `event_entry["msgs"]`).

Actual
- Only one msg_id persists (“last writer wins”), demonstrating a classic read-modify-write race:
  - The lock is held for `load_db()` and `save_db()` individually, not for the full processing transaction.

Impact
- Under real load (retries, multiple inbound messages, parallel web workers), you can lose updates:
  - dropped messages
  - dropped HIL tasks
  - corrupted caller_step/current_step transitions

Mitigation ideas
- Make the lock cover the entire `process_msg` read→mutate→save transaction, OR migrate to a transactional store (SQLite/Postgres) with row-level locks/versioning.

### E) Multi-tenancy stress: HIL approvals can 404 (tenant-aware listing vs default-db approval)
What I tested
- Playwright E2E from booking → offer → Step5 manager approval → site visit prompt, with `TENANT_HEADER_ENABLED=1`.
- Approving the Step5 task via UI (`POST /api/tasks/{id}/approve`).

Expected
- The pending task shown in the Manager panel should be approvable.
- Approving should append an assistant reply (Step5 approval → “Let’s continue with site visit bookings…”).

Actual
- `/api/tasks/pending` is tenant-aware (uses `backend.workflow_email.load_db()` which routes to `events_{team_id}.json`).
- `/api/tasks/{id}/approve` calls `approve_task_and_send()` without a tenant-aware `db_path`, and `approve_task_and_send()` defaults to `events_database.json`.
- Result: the approve request returns 404 (`Task {id} not found`) even though the task is visible in the manager panel.
- Workaround to complete the E2E: disable tenant routing for the UI requests (strip tenant headers) so both list+approve operate on the default DB.

Impact
- In multi-tenant mode, managers can see approval tasks but cannot approve them → workflows get stuck at “Waiting on HIL”.

Mitigation ideas
- Make HIL task APIs tenant-aware end-to-end:
  - Ensure approve/reject/cleanup use the same resolved db path as tasks listing.
  - Ensure frontend approval requests include tenant headers consistently (see `atelier-ai-frontend/app/page.tsx::handleTaskAction`).

---

## Summary of “general solution” needs highlighted by these tests
- Don’t hardcode step validity per intent; compute “actionability” from gate state (pending vs verified) and intent anchors.
- Never allow reconfirm of already-verified gates; treat as NO-OP and keep parsing the rest of the message.
- Remove legacy date-change fallbacks that bypass revision-signal logic.
- Normalize incoming message text once (strip quoted history/signatures) and run all detectors on the normalized text.
- Unify gatekeeping/capture/verification as a single registry-driven system so new steps don’t require scattered code edits.

---

# Plan: Prevent Out-of-Context From Overriding Confirmations (no implementation yet)

Problem example (observed)
- Message: “Yes, Room B sounds perfect!” at Step 4
- Unified detection classified it as `confirm_date`
- Pre-route out-of-context logic dropped the message as “wrong step”
- Result: room confirmation never reaches Step 3/4 handling

Plan (step-by-step)
1) Add an “actionability arbitration” pass BEFORE out-of-context returns
- Inputs: current_step, gate states (date_confirmed, locked_room_id, offer_status), extracted entities, confirmation signals
- Output: a list of actionable intents for the *current* step (or a decision that it’s a no-op)

2) Convert raw intent → gate-aware intent
- If `confirm_date` but date is already confirmed → mark as NO-OP (do not drop message)
- If confirmation signal + room entity (e.g., “Room B”) and room is not locked → treat as room confirmation
- If confirmation signal + offer is pending at Step 4 → treat as offer acceptance confirmation
- If confirmation signal but no gate is pending → ask a clarifying question instead of silent ignore

3) Make out-of-context a last-resort filter
- Only ignore when:
  - no actionable intents exist,
  - no captured entities that map to any gate,
  - no QnA, and
  - no change request signals
- Otherwise, continue processing (capture, detour, or clarify)

4) Add conflict resolution between “confirm” and “change”
- If confirmation signal and change signal are both present, favor change only when a revision signal + bound target exist
- Otherwise treat as confirmation of the pending gate for the current step

5) Tests to add (xfail until fixed)
- Step 4: “Yes, Room B sounds perfect!” should lock/confirm room (or at least route to Step 3)
- Step 4: “Yes, that offer works” should accept offer, not confirm date
- Step 5: “Yes, date is fine. Billing address: …” should capture billing and not be dropped
- Step 7: “Yes” should confirm final step (not be treated as question)

6) Debug logging improvements (to reduce misclassification confusion)
- Log both "raw intent" and "actionable intent" + gate state snapshot
- Explicitly log why OOC was applied (e.g., "no actionable intents after arbitration")

---

# Implementation Plan (remaining work; no core fixes applied yet)

This section is meant to be “grab-and-go” for devs returning from break: each workstream lists the exact acceptance tests to turn from XFAIL → PASS and the concrete file-level changes to make.

## Current status snapshot (from `tests/specs/prelaunch/test_prelaunch_regressions.py`)

Already fixed (PASS)
- Unified detection no longer crashes when `INTENT_PROVIDER=gemini` but `GOOGLE_API_KEY` is missing (`test_unified_detection_should_fallback_when_gemini_key_missing`).
- Date reconfirmation no longer regresses steps via shortcuts (`test_shortcuts_should_not_reconfirm_date_when_already_confirmed`).

Still failing by design (XFAIL; remaining implementation work)
- Step 6/7 HIL routing gaps:
  - `test_step6_transition_blocked_should_emit_action`
  - `test_step7_deposit_request_should_emit_action`
  - `test_step7_yes_should_be_confirm`
- Out-of-context + capture invariants:
  - `test_out_of_context_should_not_drop_message_with_billing`
  - `test_out_of_context_should_still_persist_step1_updates`
  - `test_step7_gatekeeper_should_treat_captured_billing_as_ready`
- Anchoring / false date-change hazards:
  - `test_step5_quoted_history_date_should_not_trigger_change`
  - `test_step7_deposit_paid_with_payment_date_should_not_detour_to_step2`
  - `test_step1_can_overwrite_event_date_from_unanchored_date`
- Step1 intent interference:
  - `test_step1_confirm_date_should_not_trigger_offer_acceptance`
- Hybrid-mode validation:
  - `test_validate_hybrid_mode_should_fail_when_required_keys_missing`
- Concurrency:
  - `test_concurrent_process_msg_can_lose_updates`

## Workstreams (implementation-ready)

### 1) Step 6/7 HIL routing + tenant-safe approvals (P0)

Goal
- Any step can emit approval-required drafts and they reliably show up as tasks + generate `actions` on finalize.
- In multi-tenant mode (`TENANT_HEADER_ENABLED=1`), listing and approving tasks must operate on the SAME tenant DB.

Primary acceptance criteria
- Turn these XFAIL → PASS:
  - `test_step6_transition_blocked_should_emit_action`
  - `test_step7_deposit_request_should_emit_action`
  - `test_step7_yes_should_be_confirm`
- Manual verification:
  - In multi-tenant mode, approving a visible task in the UI must return 200 (not 404) and remove the task from the list.

Work plan
1) Remove step whitelist in HIL enqueue + action routing
   - Problem: `enqueue_hil_tasks()` currently skips step 6/7.
   - Change: treat drafts as a capability; derive task types from draft metadata, not `current_step in {2,3,4,5}`.
   - Likely files:
     - `backend/workflows/runtime/hil_tasks.py`
     - `backend/workflow_email.py` (`_finalize_output` call sites / `actions` propagation)

2) Make approve/reject tenant-aware end-to-end (fixes the Playwright 404)
   - Problems:
     - `/api/tasks/pending` loads a tenant DB via `backend.workflow_email.load_db()`.
     - `/api/tasks/{id}/approve` calls `approve_task_and_send()` without a tenant-aware `db_path`, and `approve_task_and_send()` defaults to `events_database.json`.
     - Frontend approval requests do not include tenant headers (see `atelier-ai-frontend/app/page.tsx::handleTaskAction`).
   - Change options (pick one):
     - Option A (recommended): move tenant path resolution into a shared helper (e.g., `backend/workflows/io/database.py`) and use it in `hil_tasks.py` instead of `_get_default_db_path`.
     - Option B: in `backend/api/routes/tasks.py`, pass the resolved tenant `db_path` to `wf_approve_task_and_send(..., db_path=...)` and `wf_reject_task_and_send(..., db_path=...)`.
   - Likely files:
     - `backend/workflows/runtime/hil_tasks.py`
     - `backend/api/routes/tasks.py`
     - `atelier-ai-frontend/app/page.tsx` (add tenant headers to approve/reject POSTs)

3) Normalize what “confirm” means for Step7
   - Problem: bare “Yes” is not treated as confirm in Step7 classification.
   - Change: treat `signals.is_confirmation` / simple affirmative tokens as confirm when final confirmation is pending.
   - Likely files:
     - `backend/workflows/steps/step7_confirmation/trigger/classification.py`

4) Add a tenant-scoped regression test (recommended)
   - Add an XFAIL → PASS test proving:
     - tasks are listed under tenant header
     - approve works under the same tenant header
   - Likely location:
     - `tests/specs/prelaunch/test_prelaunch_regressions.py` (new test) or `backend/tests/api/test_tasks_tenant_context.py`

### 2) Out-of-context must not drop capture/persistence (P0)

Goal
- “Confirm-anytime” for already-verified gates becomes NO-OP (not a reason to drop the message).
- Multi-signal emails must still capture billing/company/etc even if one sub-intent is out-of-context.
- Msg ids + audit should persist even when a message is ignored (no silent loss).

Primary acceptance criteria
- Turn these XFAIL → PASS:
  - `test_out_of_context_should_not_drop_message_with_billing`
  - `test_out_of_context_should_still_persist_step1_updates`
  - `test_step7_gatekeeper_should_treat_captured_billing_as_ready`

Work plan
1) Refactor out-of-context to be “last resort”
   - OOC should only halt when:
     - there are no actionable intents after gate-aware arbitration AND
     - nothing was captured AND
     - there is no QnA/change request
   - Likely files:
     - `backend/workflows/runtime/pre_route.py`

2) Add a shared capture pipeline (capture-first)
   - Persist extracted fields (billing/company/contact) before any early return path.
   - Likely files:
     - `backend/workflows/runtime/pre_route.py` (pipeline hook)
     - `backend/workflows/common/gatekeeper.py` (use captured values in gate readiness)

3) Ensure every early return flushes persistence
   - Out-of-context currently halts before msg_id/audit persistence for some paths.
   - Likely files:
     - `backend/workflow_email.py` (persistence flush ordering)

### 3) Anchoring + “no unbound date overwrites” (P0)

Goal
- A date/time mention must never overwrite event date unless it’s clearly an event-date change request.
- Deposit/payment dates and quoted-thread dates must be treated as non-event context unless revision signals + bound target exist.

Primary acceptance criteria
- Turn these XFAIL → PASS:
  - `test_step5_quoted_history_date_should_not_trigger_change`
  - `test_step7_deposit_paid_with_payment_date_should_not_detour_to_step2`
  - `test_step1_can_overwrite_event_date_from_unanchored_date`

Work plan
1) Normalize/segment inbound text before any detection
   - Strip quoted history (“On X wrote:”, “> …”) and forwarded headers.
   - Likely files:
     - `backend/workflow_email.py` (single normalization entrypoint)

2) Require “revision signal + bound target” for date changes everywhere
   - Ensure Step1 / Step5 / Step7 date detours use the SAME rule (single source of truth).
   - Likely files:
     - `backend/workflows/steps/step1_intake/trigger/step1_handler.py`
     - `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py`
     - `backend/workflows/steps/step7_confirmation/trigger/step7_handler.py`

### 4) Hybrid mode validation (P1)

Goal
- `validate_hybrid_mode()` should reflect runtime reality: configured provider + missing key should be invalid (unless an explicit fallback path is active).

Primary acceptance criteria
- Turn this XFAIL → PASS:
  - `test_validate_hybrid_mode_should_fail_when_required_keys_missing`

Work plan
1) Extend `validate_hybrid_mode` to check key presence for configured providers
   - If intent/entity provider is gemini → require `GOOGLE_API_KEY` (or documented alternative).
   - If verbalizer is openai → require `OPENAI_API_KEY`.
   - Decide policy for dev/macOS Keychain:
     - Option A: call `load_keychain_env()` during validation (dev-friendly).
     - Option B: validation checks only env, and keychain is considered an implementation detail (prod-aligned).
   - Likely files:
     - `backend/llm/provider_config.py`

### 5) DB concurrency correctness (P1)

Goal
- Concurrent turns do not lose updates (at minimum: msg ids, audit, and tasks are not dropped).

Primary acceptance criteria
- Turn this XFAIL → PASS:
  - `test_concurrent_process_msg_can_lose_updates`

Work plan (pragmatic first)
1) Hold the file lock for the full read→mutate→save transaction
   - Simplest correctness-first fix (expect throughput trade-offs).
2) If lock duration is too costly (LLM calls), switch to one of:
   - per-thread lock files (reduce contention)
   - optimistic versioning + merge on conflict
   - migrate to SQLite/Postgres
   - Likely files:
     - `backend/workflow_email.py`
     - `backend/workflows/io/database.py`

### 6) Cleanup: urllib3 v2 / LibreSSL warning (P2)

Goal
- Remove runtime dependency warnings that can mask real errors.

Plan
- Short term: pin `urllib3<2.0` in dependencies.
- Long term: upgrade Python/OpenSSL toolchain so urllib3 v2 works without warnings.

## Architectural (Future Work)
1) StepSpec/GateSpec registries
- Central registry of steps + gates (so rules are step-agnostic where they should be).

2) Global capture pipeline
- Capture entities at any step, persist them, and auto-verify when it’s their turn.

3) HIL task routing for all steps
- Remove the `{2,3,4,5}` whitelist so Step6/7 approval-required drafts generate tasks/actions too.

4) Unified confirmation handler (addresses the “confirm_date misfire drops room confirmation” issue)
Current code reality (why misroutes happen today)
- “Confirmation” is represented in multiple inconsistent ways:
  - Unified LLM intent labels (`confirm_date`, `accept_offer`, etc.) + `signals.is_confirmation`
  - Step-local keyword classifiers (e.g., Step7 `CONFIRM_KEYWORDS`)
  - Smart shortcuts inferring `date_confirmation` purely from extracted date/time in `user_info`
  - Pre-route out-of-context uses a static step map keyed by the *raw intent label* and can ignore the whole message before routing.
- This creates the failure mode you observed:
  - Message “Yes, Room B sounds perfect!” at Step4
  - Detector mislabels as `confirm_date`
  - Out-of-context drops it (because `confirm_date` is step2-only)
  - The room confirmation never reaches Step3/Step4 logic.

Proposed architecture
- Replace “many confirmation intents” with ONE confirmation signal + a gate-aware target resolver:
  - Detector output: `intent="confirm"` (or just rely on `signals.is_confirmation=True`)
  - Resolver decides *what is being confirmed* based on gate state + extracted entities + context.

Gate-aware routing rule (the core idea)
- Single confirmation intent routed by context:
  - Date pending → confirm date (Step2 owner)
  - Room pending → confirm/lock room (Step3 owner)
  - Offer pending → accept offer / proceed to send offer (Step4/5 owner)
  - Deposit pending → handle deposit-paid / deposit-proof (Step7 owner)
  - If nothing is pending → NO-OP + continue processing (capture/QnA), or ask “What are you confirming?”

Suggested implementation (incremental, compatible with today’s code)
1. Add a pure “pending gates snapshot” helper (minimal GateSpec v0)
   - Input: `event_entry`
   - Output: ordered list of pending gates, e.g. `["date", "room", "offer", "billing", "deposit"]`
   - Use existing state where possible:
     - date pending: `not date_confirmed` or missing `requested_window.start/end/tz`
     - room pending: missing `locked_room_id`
     - offer pending: `offer_status` not in accepted/sent states (align with guards)
     - billing pending: missing `event_data.Company` or `event_data.Billing Address` (and later: consider captured values)
     - deposit pending: deposit required and not paid (canonicalize deposit schema first or via one computed gate)

2. Add a `resolve_confirmation_target(...)` arbiter (pure function)
   - Inputs:
     - message text (normalized), `unified_result.signals`, extracted entities (`user_info`), `event_entry`
   - Output:
     - `target_gate` (date/room/offer/billing/deposit/none/ambiguous)
     - `action` (confirm, noop, ask_clarify, treat_as_change)
     - `reason` for trace/debug
   - Deterministic precedence (example):
     1) If message contains a room mention and room gate is pending → room
     2) Else if message contains accept/approve language and offer gate pending → offer
     3) Else if message contains date/time and date gate pending → date
     4) Else if message contains billing fields and billing gate pending → billing
     5) Else if deposit gate pending and message contains “paid/sent/transferred” → deposit
     6) Else if exactly one gate is pending → confirm that one
     7) Else → ask a clarifying question (don’t silently ignore)

3. Integrate arbiter before out-of-context filtering
   - In pre-route:
     - If confirmation signal is present, run arbiter first.
     - If arbiter returns an actionable target, bypass OOC (or rewrite `intent` to an always-valid internal intent like `confirm_gate` + `target_gate`).
     - If arbiter returns NO-OP, continue to capture/QnA instead of dropping.

4. Enforce “no reconfirm” via idempotency checks inside the arbiter
   - If target gate already verified and value matches → NO-OP
   - If target gate verified but user proposes a different value:
     - treat as change only with revision signal + bound target (so payment dates / quoted dates don’t corrupt event date)

Benefits
- Removes the need to hardcode many step-specific confirm intents in the detector.
- Gives one consistent arbitration path for confirmations, so OOC no longer overrides real confirmations.
- Makes “confirm anytime” correct: confirms only pending gates, never reconfirms.

Trade-offs
- Requires a reliable gate-state snapshot (richer than today's `INTENT_VALID_STEPS` mapping).
- Needs careful conflict handling for multi-signal messages (confirm + change + QnA in one email).

---

# Implemented Fixes (Jan 2026)

## Summary Table

| Fix | Priority | Problem | Solution | Files Modified |
|-----|----------|---------|----------|----------------|
| **Fix 1** | P0 | Room confirmations dropped as OOC | Gate-aware intent arbitration | `pre_route.py`, `intent_executor.py` |
| **Fix 2** | P0 | Shortcuts reconfirm already-confirmed dates | Guard in `parse_date_intent()` | `date_handler.py` |
| **Fix 3** | P0 | Legacy fallback overwrites dates without revision signal | Deleted legacy fallback | `step1_handler.py` |
| **Fix 4** | P1 | OOC drops billing content | Early capture at pipeline step 0.55 | `pre_route.py` |
| **Fix 5** | P1 | Quoted email history triggers false detours | Message normalization | `message_normalize.py`, `workflow_email.py` |
| **Fix 6** | P2 | Guards force Step 2 on date mismatch | Removed mismatch condition when date confirmed | `guards.py` |
| **Fix 7** | P1 | Step 6/7 HIL tasks not created | Extended step whitelist to {2-7}, added TaskTypes | `hil_tasks.py`, `vocabulary.py` |
| **Fix 8** | P2 | Step 7 "yes" not classified as confirm | Added "yes" to CONFIRM_KEYWORDS | `constants.py` |
| **Fix 9** | P1 | Tenant-safe HIL approvals (404 bug) | Tenant-aware db_path resolution | `hil_tasks.py` |
| **Fix 10** | P1 | OOC drops msg_id without recording | Tag msg_id before OOC returns | `pre_route.py` |
| **Fix 11** | P1 | OOC drops billing/capturable data | Bypass OOC when capturable fields exist | `pre_route.py` |

**Test Status** (as of 2026-01-06):
- Prelaunch regression tests: 7 passing, 7 xfailed
- Detection + Flow tests: 520+ passing
- New normalization tests: 18 passing
- E2E verified: Complete booking flow to site visit ✅

---

## Fix 1: Gate-Aware Intent Arbitration (P0)

**Date**: 2026-01-06
**Files Modified**:
- `backend/workflows/runtime/pre_route.py`
- `backend/workflows/planner/intent_executor.py`

**Problem Solved**:
- "Yes, Room A sounds perfect!" was being dropped as out-of-context because:
  1. Detector classified it as `confirm_date` or `accept_offer`
  2. OOC check saw step-specific intent at wrong step → dropped entire message
  3. `room_pending_decision` wasn't set because shortcuts run AFTER OOC check

**Solution Implemented**:
- Added Case 2b to `_arbitrate_intent()` in `pre_route.py`:
  - Room mentions at Step 2/3/4 WITHOUT `room_pending_decision` are now allowed through
  - If user explicitly mentions a room name and room isn't locked, remap to `room_confirmation`

---

## Fix 2: Reconfirmation Hazard Guard (P0)

**Date**: 2026-01-06
**Files Modified**: `backend/workflows/planner/date_handler.py`

**Problem Solved**:
- `parse_date_intent()` would create `date_confirmation` intent even when date was already confirmed
- This could cause unnecessary detours and state confusion

**Solution Implemented**:
- Added guard at line 363: Skip if `date_confirmed=True` to prevent reconfirmation hazard

---

## Fix 3: Legacy Date Fallback Removed (P0)

**Date**: 2026-01-06
**Files Modified**: `backend/workflows/steps/step1_intake/trigger/step1_handler.py`

**Problem Solved**:
- Legacy fallback at lines 965-994 would overwrite `chosen_date` with ANY extracted date
- This bypassed revision-signal validation, allowing deposit payment dates to corrupt event dates

**Solution Implemented**:
- Deleted the dangerous fallback entirely
- All date changes now routed through `detect_change_type_enhanced()` which requires revision signal + bound target

---

## Fix 4: Early Field Capture Before OOC Check (P1)

**Date**: 2026-01-06
**Files Modified**: `backend/workflows/runtime/pre_route.py`

**Problem Solved**:
- Out-of-context check at pipeline step 0.6 could drop entire message, including billing info
- Multi-intent messages (confirm + billing) would lose the billing capture

**Solution Implemented**:
- Added early capture at pipeline step 0.55 (before OOC check)
- `capture_user_fields()` now runs BEFORE out-of-context filtering
- Ensures billing, dates, rooms are persisted even if intent is later dropped

---

## Fix 5: Message Normalization (P1)

**Date**: 2026-01-06
**Files Created**: `backend/workflows/common/message_normalize.py`
**Files Modified**: `backend/workflow_email.py`

**Problem Solved**:
- Quoted email history (e.g., "On Jan 5 wrote:") triggered false detours
- Deposit payment dates in quoted history would corrupt event dates

**Solution Implemented**:
- Created `normalize_email_body()` function with:
  - `strip_quoted_lines()` - removes `>` prefixed lines
  - `strip_forwarded_headers()` - removes "On X wrote:" sections
  - `strip_signature()` - removes `-- ` signatures
- Integrated into `workflow_email.py` at message processing

---

## Fix 6: Guards Date Mismatch Bug (P2)

**Date**: 2026-01-06
**Files Modified**: `backend/workflow/guards.py`

**Problem Solved**:
- Guards at line 119 forced Step 2 when extracted date differed from chosen_date
- This bypassed the change detection system (which requires revision signals)
- Deposit payment dates would trigger Step 2 detour

**Solution Implemented**:
- Removed the date mismatch condition when date is already confirmed
- Added explanatory comment: date CHANGES are handled by `detect_change_type_enhanced()` which requires revision signal
- Guards now only force Step 2 when `not date_confirmed`

---

## Fix 7: HIL Routing for Step 6/7 (P1)

**Date**: 2026-01-06
**Files Modified**:
- `backend/domain/vocabulary.py`
- `backend/workflows/runtime/hil_tasks.py`

**Problem Solved**:
- Step 6/7 drafts with `requires_approval: True` never generated HIL tasks
- The step whitelist `{2, 3, 4, 5}` excluded Steps 6 and 7
- No `TaskType` values existed for transition or confirmation messages

**Solution Implemented**:
- Added new TaskType enum values:
  - `TRANSITION_MESSAGE = "transition_message"` for Step 6
  - `CONFIRMATION_MESSAGE = "confirmation_message"` for Step 7
- Extended `_hil_action_type_for_step()` to return action types for steps 6 and 7
- Changed whitelist from `{2, 3, 4, 5}` to `{2, 3, 4, 5, 6, 7}`
- Added task type mapping for step 6 → TRANSITION_MESSAGE, step 7 → CONFIRMATION_MESSAGE

**Test Results**:
- `test_step6_transition_blocked_should_emit_action` now passes
- `test_step7_deposit_request_should_emit_action` now passes

---

## Remaining Work

### Actionable (Next Priority)
1. **Concurrent DB access** - Last-writer-wins race condition under parallel processing

### Architectural (Future Work)
1. StepSpec/GateSpec registries - Central registry of steps + gates
2. Global capture pipeline - Capture entities at any step with auto-verification
3. Unified confirmation handler - Single confirmation intent with gate-aware routing
4. **Multilingual confirmation detection** - Replace keyword matching with sentiment-based classifier for i18n support (works across German/English/French etc.)

### Xfailed Tests (7 remaining)
These require architectural changes:
- Anchoring + unbound date overwrites (4 tests)
- Hybrid mode validation (AGENT_MODE detection)
- Concurrent DB access patterns
- Gatekeeper captured billing/company tracking
