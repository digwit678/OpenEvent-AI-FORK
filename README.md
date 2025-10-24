# OpenEvent Workflow

## Purpose & Scope
OpenEvent automates The Atelier’s end-to-end venue booking flow: it ingests client emails, maintains a deterministic event record, and coordinates human-in-the-loop approvals so every outbound message aligns with the Management Plan and Workflow v3 blueprint.【F:backend/workflows/groups/intake/trigger/process.py†L30-L207】【F:backend/workflow_email.py†L86-L145】 The pipeline tracks venue statuses (Lead → Option → Confirmed) while preserving audit trails and reversible detours across Steps 1–7.【F:backend/domain/models.py†L24-L60】【F:backend/workflows/groups/event_confirmation/trigger/process.py†L293-L360】

## Workflow at a Glance
1. **Step 1 – Intake:** Classify intent, capture client context, seed requirements, and detour if the date or room needs clarification.【F:backend/workflows/groups/intake/trigger/process.py†L33-L184】  
2. **Step 2 – Date Confirmation:** Offer deterministic slots or log a confirmed date and link it to the event record.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L44-L159】  
3. **Step 3 – Room Availability:** Evaluate room inventory, cache decisions, and stage HIL approvals before locking a room.【F:backend/workflows/groups/room_availability/trigger/process.py†L60-L316】  
4. **Step 4 – Offer:** Normalize products, compose pricing, version offers, and queue a draft for review.【F:backend/workflows/groups/offer/trigger/process.py†L39-L233】  
5. **Step 5 – Negotiation:** Interpret replies (accept / decline / counter / clarification) and route structural changes back to prior steps.【F:backend/workflows/groups/negotiation_close.py†L47-L200】  
6. **Step 6 – Transition Checkpoint:** Block confirmation until date, room, offer, and deposit prerequisites are satisfied.【F:backend/workflows/groups/transition_checkpoint.py†L28-L88】  
7. **Step 7 – Confirmation:** Manage deposits, reserves, site visits, declines, and final confirmations through audited HIL gates.【F:backend/workflows/groups/event_confirmation/trigger/process.py†L71-L360】

## How to Review a Message Like the System
1. **Load state:** Fetch the event’s `current_step`, `caller_step`, and `thread_state` from the database (mirroring `process_msg`).【F:backend/workflow_email.py†L102-L145】  
2. **Apply entry guard:** Inspect the step’s entry checks (date present, room locked, etc.) and decide whether to detour using the same conditions the code enforces.【F:backend/workflows/groups/intake/trigger/process.py†L122-L184】【F:backend/workflows/groups/transition_checkpoint.py†L28-L70】  
3. **Decide action:** Follow the step’s deterministic branch (e.g., accept vs. counter) and honour any HIL gate before sending drafts.【F:backend/workflows/groups/negotiation_close.py†L75-L200】【F:backend/workflows/groups/event_confirmation/trigger/process.py†L75-L360】  
4. **Persist safely:** Update metadata, hashes, and audit logs exactly as the helper methods do so later steps can validate caching and status transitions.【F:backend/workflows/groups/room_availability/trigger/process.py†L95-L315】【F:backend/workflows/groups/offer/trigger/process.py†L201-L233】

## Local Verification
Run the curated workflow regression suites with a stubbed LLM adapter:
```bash
# Core parity checks (Steps 1–3)
pytest backend/tests/workflows/test_workflow_v3_alignment.py::test_intake_guard_manual_review \
       backend/tests/workflows/test_workflow_v3_alignment.py::test_step2_five_date_loop_and_confirmation \
       backend/tests/workflows/test_workflow_v3_alignment.py::test_happy_path_step3_to_4_hil_gate

# Offer-to-confirmation scenarios (Steps 4–7)
pytest backend/tests/workflows/test_workflow_v3_steps_4_to_7.py
```
These suites stub the agent adapter, feed deterministic inputs, and assert persisted fields, audit events, and draft requirements at every stage.【F:backend/tests/workflows/test_workflow_v3_alignment.py†L16-L148】【F:backend/tests/workflows/test_workflow_v3_steps_4_to_7.py†L33-L318】

## Privacy & Data-Access Model (Developer Focus)
- **Identity:** Clients are keyed by lowercased email, ensuring per-user isolation across client, event, and task collections.【F:backend/workflows/io/database.py†L131-L173】  
- **Context budget:** Context snapshots include profile, last five history previews, the latest event, and a `context_hash` for cache validation—no other users’ data is ever injected.【F:backend/workflows/io/database.py†L190-L206】  
- **History redaction:** Message previews are capped at 160 characters and store intent/confidence, not full bodies.【F:backend/workflows/io/database.py†L149-L164】  
- **LLM boundary:** Trigger groups pass curated JSON (intent classification, structured fields, pricing inputs) to adapters; drafts remain HIL-gated before any outbound send.【F:backend/workflows/groups/intake/llm/analysis.py†L10-L20】【F:backend/workflows/groups/offer/trigger/process.py†L39-L93】【F:backend/workflows/common/types.py†L75-L80】  
- **No unscoped reads:** Helpers such as `last_event_for_email` and `find_event_idx` always filter by the current email, preventing cross-user leakage even when names collide.【F:backend/workflows/io/database.py†L175-L227】

## Glossary
- **Lead / Option / Confirmed:** Event lifecycle statuses stored in metadata and mirrored into `event_data` for legacy tooling.【F:backend/domain/models.py†L24-L60】【F:backend/workflows/io/database.py†L242-L259】  
- **Caller Step:** Previous step recorded before a detour so the workflow can return after satisfying prerequisites.【F:backend/workflows/groups/intake/trigger/process.py†L122-L205】【F:backend/workflows/groups/negotiation_close.py†L51-L176】  
- **Requirements Hash:** Stable hash of seating, participants, duration, special needs, and preferred room used to cache room evaluations.【F:backend/workflows/groups/intake/trigger/process.py†L111-L175】  
- **Room Eval Hash:** Stored once HIL approves Step 3, proving the locked room matches the current requirements.【F:backend/workflows/groups/room_availability/trigger/process.py†L287-L315】  
- **Transition Ready:** Boolean flag set by Step 6 to signal confirmation prerequisites are met.【F:backend/workflows/groups/transition_checkpoint.py†L54-L70】  
- **Context Hash:** SHA256 signature of the bounded client snapshot for cache keys and auditing.【F:backend/workflows/io/database.py†L190-L206】

## Self-Tests (Copy/Paste Scenarios)
Use the stubbed agent harness from the tests or the CLI adapter to simulate these flows.

**A. No date → ask_for_date task → confirm → proceed**  
1. Send a low-information inquiry without a date; expect `manual_review_enqueued` or `date_options_proposed` with candidate slots.  
2. Reply with `info={"date": "2025-03-15"}` to confirm the date; expect Step 3 hand-off.  
3. Verify event metadata stores `chosen_date` and `date_confirmed=True`.【F:backend/tests/workflows/test_workflow_v3_alignment.py†L91-L114】【F:backend/workflows/groups/intake/trigger/process.py†L157-L168】

**B. Date provided → Step 3 availability OK → Step 4 offer**  
1. Send an intake message with ISO date, participants, and preferred room.  
2. Confirm HIL approval for the room (`hil_approve_step=3`); expect `offer_draft_prepared`.  
3. Check event `current_step==5`, `locked_room_id` set, and hashes aligned.【F:backend/tests/workflows/test_workflow_v3_alignment.py†L117-L148】【F:backend/tests/workflows/test_workflow_v3_steps_4_to_7.py†L39-L64】

**C. Room unavailable → alternatives → detour to Step 2 → resume Step 3**  
1. Trigger Step 3 with feedback `room_feedback="not_good_enough"` and higher participant count to demand a larger room.  
2. Observe alternative dates appended to the draft and `caller_step` recorded.  
3. Follow the detour to Step 2 to pick a new date, then re-run Step 3 and approve via HIL.【F:backend/workflows/groups/room_availability/trigger/process.py†L83-L205】【F:backend/tests/workflows/test_workflow_v3_steps_4_to_7.py†L97-L134】

**D. Product updates loop → refreshed offer → acceptance**  
1. After `_bootstrap_to_offer`, send `products_add` updates; ensure offer version increments and prior drafts are superseded.  
2. Reply “We accept the offer” to enter Step 6 with acceptance draft queued.【F:backend/tests/workflows/test_workflow_v3_steps_4_to_7.py†L69-L118】【F:backend/workflows/groups/offer/trigger/process.py†L201-L233】【F:backend/workflows/groups/negotiation_close.py†L75-L116】

**E. Negotiation counter → manual review → accept → Steps 6 & 7**  
1. Submit four consecutive counteroffers; the fourth should enqueue `negotiation_manual_review`.  
2. After manager review, send an acceptance and confirm Step 6 unlocks Step 7 via `transition_ready`.【F:backend/tests/workflows/test_workflow_v3_steps_4_to_7.py†L115-L188】【F:backend/workflows/groups/transition_checkpoint.py†L28-L70】

**F. Deposit required → Option → deposit paid → Confirmed**  
1. Mark `deposit_state={"required": True, "percent": 30, "status": "required"}` before confirmation.  
2. Client confirms; expect `confirmation_deposit_requested` and status staying Option.  
3. After a “deposit paid” reply and HIL approval, ensure status advances to Confirmed.【F:backend/tests/workflows/test_workflow_v3_steps_4_to_7.py†L252-L274】【F:backend/workflows/groups/event_confirmation/trigger/process.py†L150-L233】

**G. Context reuse: same user later → prior preferences surfaced**  
1. Send two separate leads from the same email; confirm history previews and last event details appear in the context payload.  
2. Verify `context_hash` changes only when history/profile updates occur.【F:backend/workflows/io/database.py†L149-L206】【F:backend/workflows/groups/intake/trigger/process.py†L41-L205】

**H. Isolation: different user, similar name/email typo → no leakage**  
1. Create events for `client@example.com` and `client+1@example.com`.  
2. Confirm lookups via `last_event_for_email` and `find_event_idx` keep records separate, even if names match.  
3. Ensure context snapshots never include the other client’s history.【F:backend/workflows/io/database.py†L175-L227】【F:backend/workflows/io/database.py†L190-L206】

