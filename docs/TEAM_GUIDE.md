# OpenEvent Workflow Team Guide

## Overview
- **Actors & responsibilities**
  - *Trigger nodes* (purple) parse incoming client messages and orchestrate state transitions for each workflow group.【F:backend/workflows/groups/intake/trigger/process.py†L30-L207】【F:backend/workflow_email.py†L86-L145】
  - *LLM nodes* (green/orange) classify intent, extract structured details, and draft contextual replies while keeping deterministic inputs such as product lists and pricing stable.【F:backend/workflows/groups/intake/llm/analysis.py†L10-L20】【F:backend/workflows/groups/offer/trigger/process.py†L39-L93】
  - *OpenEvent Actions / HIL gates* (light-blue) capture manager approvals, enqueue manual reviews, and persist audited decisions before messages can be released to clients.【F:backend/workflows/groups/room_availability/trigger/process.py†L246-L316】【F:backend/workflows/groups/offer/trigger/process.py†L46-L78】【F:backend/workflows/groups/event_confirmation/trigger/process.py†L293-L360】
- **Lifecycle statuses** progress from **Lead → Option → Confirmed**, with cancellations tracked explicitly; these values are stored in both `event.status` metadata and the legacy `event_data` mirror.【F:backend/domain/models.py†L24-L60】【F:backend/workflows/io/database.py†L242-L259】【F:backend/workflows/groups/event_confirmation/trigger/process.py†L260-L318】
- **Context snapshots** are bounded to the current user: the last five history entries plus the newest event, redacted to previews, and hashed via `context_hash` for cache safety.【F:backend/workflows/io/database.py†L190-L206】【F:backend/workflows/common/types.py†L47-L80】

## How control flows (Steps 1–7)
Each step applies an entry guard, deterministic actions, and explicit exits/detours.

### Step 1 — Intake & Data Capture
- **Entry guard:** Incoming mail is classified; anything below 0.85 confidence or non-event intent is routed to manual review with a draft holding response.【F:backend/workflows/groups/intake/trigger/process.py†L33-L100】
- **Primary actions:** Upsert client by email, append history, capture bounded context, create or refresh the event record, merge profile updates, and compute `requirements_hash` for caching.【F:backend/workflows/groups/intake/trigger/process.py†L41-L205】
- **Detours & exits:** Missing or updated dates/requirements trigger `caller_step` bookkeeping and reroute to Step 2 or 3 while logging audit entries.【F:backend/workflows/groups/intake/trigger/process.py†L122-L184】
- **Persistence:** Event metadata stores requirements, hashes, chosen date, and resets room evaluation locks as needed.【F:backend/workflows/groups/intake/trigger/process.py†L111-L168】

### Step 2 — Date Confirmation
- **Entry guard:** Requires an event record; otherwise halts with `date_invalid`. If no confirmed date, proposes deterministic slots via `suggest_dates`.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L21-L90】
- **Actions:** Resolve the confirmed date from user info (ISO or DD.MM.YYYY), tag the source message, update `chosen_date/date_confirmed`, and link the event back to the client profile.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L92-L158】
- **Reminder:** Clients often reply with just a timestamp (e.g. `2027-01-28 18:00–22:00`) when a thread is already escalated. `_message_signals_confirmation` explicitly treats these bare date/time strings as confirmations; keep this heuristic in place whenever adjusting Step 2 detection so we don’t re-open manual-review loops for simple confirmations.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L1417-L1449】
- **Guardrail:** `_resolve_confirmation_window` normalizes parsed times, drops invalid `end <= start`, backfills a missing end-time by scanning the message, and now maps relative replies such as “Thursday works”, “Friday next week”, or “Friday in the first October week” onto the proposed candidate list before validation. Preserve this cleanup so confirmations don’t regress into “end time before start time” loops or re-trigger HIL drafts.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L1527-L1676】
- **Parser upgrade:** `parse_first_date` falls back to `resolve_relative_date`, so relative phrasing (next week, next month, ordinal weeks) is converted to ISO dates before downstream checks. Pass `allow_relative=False` only when you deliberately need raw numeric parsing, as `_determine_date` does prior to candidate matching.【F:backend/workflows/common/datetime_parse.py†L102-L143】【F:backend/workflows/common/relative_dates.py†L18-L126】
- **Exits:** Returns to caller if invoked from a detour, otherwise advances to Step 3 with in-progress thread state and an approval-ready confirmation draft.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L125-L159】

#### Regression trap: quoted confirmations triggering General Q&A
- **Root cause:** Email clients quote the entire intake brief beneath short replies such as `2026-11-20 15:00–22:00`. `detect_general_room_query` sees that quoted text, flags `is_general=True`, we dive into `_present_general_room_qna`, emit the “It appears there is no specific information available” fallback, and Step 3 never autoloads even though the client just confirmed the slot.
- **Guardrail:** After parsing `state.user_info`, Step 2 now forces `classification["is_general"]=False` whenever we already extracted `date/event_date` or `_message_signals_confirmation` matched the reply, so `_resolve_confirmation_window` executes immediately regardless of the quoted text.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L721-L741】
- **Backfill:** When the extractor misses the ISO string entirely, Step 1 now re-parses `YYYY-MM-DD HH:MM–HH:MM` replies before classification and populates `date/event_date/start_time/end_time` so Step 2 can auto-confirm and trigger Step 3 instead of falling into the “Next step” stub.【F:backend/workflows/groups/intake/trigger/process.py†L208-L321】
- **Rule:** Do **not** resurrect that fallback to mask missing structured payloads—if Step 3 fails, surface a clear error instead of looping managers on the “Next step” stub.

### Step 3 — Room Availability (no HIL)
- **Entry guard:** Requires a chosen date; otherwise detours to Step 2 and records caller provenance.【F:backend/workflows/groups/room_availability/trigger/process.py†L51-L121】
- **Actions:** Re-evaluate inventory when requirements change, select the best room, draft outcome messaging, compute alternatives. No manager review is enqueued at this step; drafts are always `requires_approval=False` and stale step-3 HIL requests are cleared on entry.【F:backend/workflows/groups/room_availability/trigger/process.py†L120-L205】【F:backend/workflow_email.py†L280-L360】
- **Caching:** If the locked room and requirement hash already match, Step 3 short-circuits and returns control to the caller without recomputing availability.【F:backend/workflows/groups/room_availability/trigger/process.py†L60-L205】
- **Regression Guard:** If you ever see a Step-3 task in the manager panel, it’s a bug. Clear `pending_hil_requests` for step=3 and ensure the room draft leaves `requires_approval` false.【F:backend/workflows/groups/room_availability/trigger/process.py†L120-L205】

### Step 4 — Offer Preparation
- **Entry guard:** Requires an event entry populated by prior steps; otherwise halts with `offer_missing_event`.【F:backend/workflows/groups/offer/trigger/process.py†L21-L33】
- **Actions:** Normalize product operations, rebuild pricing inputs, call `ComposeOffer` to generate totals, version offers, and queue a draft email for approval.【F:backend/workflows/groups/offer/trigger/process.py†L39-L93】【F:backend/workflows/groups/offer/trigger/process.py†L154-L233】
- **State updates:** Resets negotiation counters when returning from Step 5, sets `transition_ready=False`, and moves to Step 5 while clearing `caller_step`.【F:backend/workflows/groups/offer/trigger/process.py†L59-L92】
- **Heuristic guard:** Short replies like “OK add Wireless Microphone” no longer drop into manual review; Step 1 now auto-detects catalog items, injects `products_add`, and re-flags the intent as an event request so the offer loop keeps iterating instead of stalling at HIL.【F:backend/workflows/groups/intake/trigger/process.py†L201-L357】

### Step 5 — Negotiation Close
- **Entry guard:** Requires an event; otherwise halts with `negotiation_missing_event`.【F:backend/workflows/groups/negotiation_close.py†L27-L38】
- **Actions:** Classify reply intent (accept, decline, counter, clarification), detect structural changes (date, room, participants, products), and manage counter limits with manual-review escalations.【F:backend/workflows/groups/negotiation_close.py†L47-L200】
- **Detours:** Structural changes push to Steps 2–4 with `caller_step=5` recorded; counters beyond three enqueue a manual review task and hold at Step 5.【F:backend/workflows/groups/negotiation_close.py†L51-L175】
- **Exits:** Acceptances advance to Step 6; declines advance to Step 7 with draft messaging awaiting approval.【F:backend/workflows/groups/negotiation_close.py†L75-L117】

### Step 6 — Transition Checkpoint
- **Entry guard:** Requires an event; otherwise halts with `transition_missing_event`.【F:backend/workflows/groups/transition_checkpoint.py†L16-L26】
- **Actions:** Collect blockers (confirmed date, locked room, requirements hash alignment, accepted offer, deposit state) and draft clarifications if anything is outstanding.【F:backend/workflows/groups/transition_checkpoint.py†L28-L88】
- **Exit:** When blockers are clear, marks `transition_ready=True`, advances to Step 7, and records the audit trail.【F:backend/workflows/groups/transition_checkpoint.py†L54-L70】

### Step 7 — Event Confirmation & Post-Offer Handling
- **Entry guard:** Requires the current event; otherwise halts with `confirmation_missing_event`.【F:backend/workflows/groups/event_confirmation/trigger/process.py†L29-L39】
- **Actions:** Classify confirmation intent (confirm, reserve, deposit paid, site visit, decline, question) and manage deposit/site-visit subflows while tracking `confirmation_state` and optional calendar blocks.【F:backend/workflows/groups/event_confirmation/trigger/process.py†L71-L358】
- **HIL gate:** `hil_approve_step==7` routes through `_process_hil_confirmation`, ensuring final drafts, declines, deposits, and site-visit notices are human-approved before sending and updating status to Confirmed.【F:backend/workflows/groups/event_confirmation/trigger/process.py†L47-L360】

## Detour, caller_step & hash rules
- `caller_step` captures the prior workflow position before detouring (e.g., Step 1 pushing to Step 2/3, Step 5 returning to Step 4) and is cleared once the caller regains control.【F:backend/workflows/groups/intake/trigger/process.py†L122-L205】【F:backend/workflows/groups/negotiation_close.py†L51-L176】
- `requirements_hash` snapshots requirement changes; Step 3 updates `room_eval_hash` only after HIL approval to prove the lock matches the latest requirements.【F:backend/workflows/groups/intake/trigger/process.py†L111-L175】【F:backend/workflows/groups/room_availability/trigger/process.py†L287-L315】
- `room_pending_decision` stores the proposed room, status, summary, and hash so HIL can approve deterministically.【F:backend/workflows/groups/room_availability/trigger/process.py†L95-L115】
- `offer_sequence` and `offer_status` track versioned drafts to prevent duplicate sends; each new offer supersedes prior drafts before Step 5 negotiation resumes.【F:backend/workflows/groups/offer/trigger/process.py†L201-L233】
- `context_hash` stabilizes bounded client context for caching and audit; every snapshot is hashed before storage or reuse.【F:backend/workflows/io/database.py†L190-L206】

## Privacy & Data Access Model
- Clients are keyed by lowercased email; all lookups and event associations respect this scoped identifier.【F:backend/workflows/io/database.py†L131-L173】【F:backend/workflows/groups/intake/trigger/process.py†L41-L205】
- Context sent to downstream logic only includes the client's profile, last five history previews, the most recent event, and the derived `context_hash`; no cross-client data is exposed.【F:backend/workflows/io/database.py†L190-L206】
- Message history stores intent labels, confidence, and trimmed body previews (160 chars) to avoid leaking full correspondence while preserving auditability.【F:backend/workflows/io/database.py†L149-L164】
- Site visits and deposits honor venue policy and locked-room constraints before offering sensitive scheduling details.【F:backend/workflows/common/room_rules.py†L142-L200】【F:backend/workflows/groups/event_confirmation/trigger/process.py†L200-L358】
- Draft messages default to `requires_approval=True` ensuring HIL review before any client-facing output is sent.【F:backend/workflows/common/types.py†L75-L80】

## Where to debug each step
| Step | File(s) | Key entry point |
| --- | --- | --- |
| 1 – Intake | `backend/workflows/groups/intake/trigger/process.py` | `process`【F:backend/workflows/groups/intake/trigger/process.py†L30-L207】 |
| 2 – Date Confirmation | `backend/workflows/groups/date_confirmation/trigger/process.py` | `process`【F:backend/workflows/groups/date_confirmation/trigger/process.py†L17-L159】 |
| 3 – Room Availability | `backend/workflows/groups/room_availability/trigger/process.py` | `process` & `_apply_hil_decision`【F:backend/workflows/groups/room_availability/trigger/process.py†L28-L316】 |
| 4 – Offer | `backend/workflows/groups/offer/trigger/process.py` | `process`【F:backend/workflows/groups/offer/trigger/process.py†L17-L93】 |
| 5 – Negotiation | `backend/workflows/groups/negotiation_close.py` | `process`【F:backend/workflows/groups/negotiation_close.py†L23-L200】 |
| 6 – Transition | `backend/workflows/groups/transition_checkpoint.py` | `process`【F:backend/workflows/groups/transition_checkpoint.py†L12-L70】 |
| 7 – Confirmation | `backend/workflows/groups/event_confirmation/trigger/process.py` | `process` & `_process_hil_confirmation`【F:backend/workflows/groups/event_confirmation/trigger/process.py†L25-L360】 |
| Router | `backend/workflow_email.py` | `process_msg` loop【F:backend/workflow_email.py†L86-L145】 |

## Common user messages → expected reactions
| User message | System reaction | Notes |
| --- | --- | --- |
| “Hi, just saying hello” | Manual review task + holding draft | Low-confidence intent routes to HIL queue.【F:backend/workflows/groups/intake/trigger/process.py†L53-L100】 |
| “What dates are available?” | Draft listing five deterministic slots, waits at Step 2 | Candidate dates pulled via `suggest_dates`.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L44-L90】 |
| “Let’s switch to Room B” (during negotiation) | Detour to Step 3 with `caller_step=5` | Structural change resets negotiation counter.【F:backend/workflows/groups/negotiation_close.py†L51-L176】 |
| “Can you lower the price?” (4th time) | Manual review escalation, draft escalation note | Counter threshold triggers task creation.【F:backend/workflows/groups/negotiation_close.py†L118-L159】 |
| "Please confirm the booking" | Confirmation draft queued; awaits HIL sign-off | Deposit/site-visit logic handled before final send.【F:backend/workflows/groups/event_confirmation/trigger/process.py†L75-L318】 |
| "Deposit has been paid" | Deposit marked paid, confirmation draft regenerated | Ensures status before final confirmation.【F:backend/workflows/groups/event_confirmation/trigger/process.py†L175-L238】
| "pls add another wireless microphone" | Extracts products_add, increments quantity, regenerates offer | LLM extraction now includes products_add/products_remove fields.【F:backend/adapters/agent_adapter.py†L239-L244】【F:backend/workflows/groups/offer/trigger/process.py†L626-L634】 |

## Known Issues & Fixes

### Product Addition Not Updating Total (Fixed)
**Root Causes:**
1. **Missing LLM extraction fields:** The OpenAI adapter's extraction prompt didn't include `products_add` or `products_remove` fields, causing the LLM to return `null` for these fields even when users requested product additions.【F:backend/adapters/agent_adapter.py†L239-L244】
2. **No quantity semantics:** The system didn't understand that "another" means "+1 to existing quantity".
3. **Wrong merge logic:** `_upsert_product` was replacing quantity instead of incrementing it. When a user said "add another wireless microphone", the system would set quantity to 1 instead of adding 1 to the existing quantity.【F:backend/workflows/groups/offer/trigger/process.py†L626-L634】

**Fixes Applied:**
1. Updated `_ENTITY_PROMPT` to include: `products_add (array of {name, quantity} for items to add), products_remove (array of product names to remove). Use null when unknown. For 'add another X' or 'one more X', include {"name": "X", "quantity": 1} in products_add.`【F:backend/adapters/agent_adapter.py†L239-L244】
2. Added `products_add` and `products_remove` to `_ENTITY_KEYS` list so the extraction results are properly captured.【F:backend/adapters/agent_adapter.py†L247-L265】
3. Fixed `_upsert_product` to increment quantity: `existing["quantity"] = existing["quantity"] + item["quantity"]` instead of `existing["quantity"] = item["quantity"]`.【F:backend/workflows/groups/offer/trigger/process.py†L626-L634】

**Testing Approach:**
- Create a test event with 1 wireless microphone (quantity: 1, unit_price: 25.0)
- Simulate user message: "pls add another wireless microphone"
- Verify extraction returns: `products_add: [{"name": "Wireless Microphone", "quantity": 1}]`
- Verify `_upsert_product` increments quantity from 1 to 2
- Verify total updates from CHF 1,965.00 to CHF 1,990.00

### Product Additions Causing Duplicates (Fixed)
**Root Cause:**
When a user requests a product addition (e.g., "add a wireless microphone"), two logic paths were triggered simultaneously:
1. The `_detect_product_update_request` heuristic in Step 1 correctly identified the request and added the product to the `user_info.products_add` list.
2. The `_autofill_products_from_preferences` function in Step 4 also ran, saw that "wireless microphone" was a suggested item in the original preferences, and added it *again*. This resulted in the quantity increasing by two instead of one.

**Fix:**
The `_autofill_products_from_preferences` function in `backend/workflows/groups/offer/trigger/process.py` was updated to prevent it from running if products have already been manually modified in the same turn. It now checks `_has_offer_update(user_info)` before proceeding, ensuring that explicit user requests always take precedence over automated suggestions.【F:backend/workflows/groups/offer/trigger/process.py†L405-L410】

### Offer Acceptance Stuck / Not Reaching HIL (Fixed)
**Symptoms:** Client replies “ok that’s fine / approved / continue / please send” but the workflow stays at Step 4 (Awaiting Client) or routes to manual review; manager/HIL never sees the offer to approve; Approve button in GUI does nothing.

**Root Causes:**
1. Acceptance phrases were classified as `other`, so Step 5 (negotiation) never ran and no HIL task was created.
2. Even when acceptance was detected later, HIL didn’t have a compact offer summary to review and approve.
3. GUI Approve relied on `hil_approve_step=5` but the state sometimes remained at Step 4.

**Fixes Applied:**
1. Intake now force-upgrades short acceptance replies to `event_request`, stamps `intent_detail=event_intake_negotiation_accept`, sets `hil_approve_step=5`, and pins the event on Step 5 with `Waiting on HIL` so negotiation close can run immediately.【F:backend/workflows/groups/intake/trigger/process.py†L538-L559】
2. Negotiation accept flow now sends a HIL-ready summary (line items + total) and keeps the thread in `Waiting on HIL` until the manager approves; HIL approval sets the offer to Accepted and advances to Step 6 automatically; rejection prompts to adjust and resend.【F:backend/workflows/groups/negotiation_close.py†L23-L47】【F:backend/workflows/groups/negotiation_close.py†L98-L170】【F:backend/workflows/groups/negotiation_close.py†L341-L394】
3. Acceptance keywords expanded to include “continue / please send / go ahead / ok that’s fine / approved” and we normalize curly apostrophes so short “that’s fine” replies are caught.【F:backend/workflows/groups/negotiation_close.py†L23-L47】【F:backend/workflows/groups/intake/trigger/process.py†L149-L167】【F:backend/workflows/groups/intake/trigger/process.py†L518-L559】
4. HIL Approve now applies the decision to the pending negotiation and runs the transition checkpoint so the workflow moves past Step 5 as soon as the manager clicks Approve (no more stuck buttons).【F:backend/workflow_email.py†L306-L359】
5. Step 4 now also recognizes acceptance phrases (with normalized quotes) and short-circuits straight to HIL with a pending decision, avoiding repeated offer drafts when clients reply “approved/continue/that’s fine” on the offer thread.【F:backend/workflows/groups/offer/trigger/process.py†L52-L123】【F:backend/workflows/groups/offer/trigger/process.py†L1115-L1131】

### Duplicate HIL sends after offer acceptance (Fixed)
**Symptoms:** Client says “that’s fine” → placeholder “sent to manager” is shown, but the full offer is re-posted to the client and multiple HIL tasks are created.

**Fixes Applied:**
1. Step 5 now detects if a negotiation decision is already pending or a step-5 HIL task exists and returns a `negotiation_hil_waiting` action without re-enqueuing tasks or re-sending the offer draft.【F:backend/workflows/groups/negotiation_close.py†L37-L61】
2. Client-facing replies for `negotiation_hil_waiting` are collapsed to a single “sent to manager” notice (no offer body) so the chat isn’t spammed while HIL is open.【F:backend/main.py†L80-L86】

**Regression Guard:** If a client restates acceptance while HIL is open, you should see one HIL task and a single waiting message; no new drafts should reach the chat.

### Spurious unavailable-date apologies on month-only requests (Fixed)
**Symptoms:** A month-only ask (“February 2026, Saturday evening”) produced “Sorry, we don't have free rooms on 20.02.2026” even though the client never mentioned that date, and the suggested list collapsed to a single date.

**Fixes Applied:**
1. `_client_requested_dates` now ignores month-only hints unless an explicit day appears in the message (dd.mm.yyyy, yyyy-mm-dd, or “12 Feb 2026”), preventing phantom “unavailable” notices.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L270-L296】
2. Window hints now sanitize `weekdays_hint` to 1–7, so mis-parsed numbers (e.g., participant counts) can’t force a single “Week 1” view and truncate the date list.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L2462-L2474】
3. When a client asks for menus alongside dates, the date proposal now includes a menu block filtered to the requested month so the hybrid question is answered in one message.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L1302-L1319】【F:backend/workflows/groups/date_confirmation/trigger/process.py†L2123-L2143】

**Regression Guard:** Month-only requests should return up to five valid options in that month (e.g., February Saturdays) with no apology about dates the client never mentioned.

### Offer re-sent while waiting on HIL (Fixed)
**Symptoms:** After a client accepts, the “sent to manager” note is shown but the offer body is posted again and multiple HIL tasks appear.

**Fixes Applied:**
1. Step 4 now short-circuits when a Step 5 HIL decision is already pending, returning `offer_waiting_hil` so no new drafts/tasks are emitted.【F:backend/workflows/groups/offer/trigger/process.py†L33-L49】
2. Client-facing replies for `offer_waiting_hil` reuse the waiting message (no offer body) to avoid spam.【F:backend/main.py†L80-L88】
3. Older HIL requests are cleaned up automatically: new reviews replace prior tasks, and Step 5 acceptance clears Step 4 offer tasks so only one manager action remains.【F:backend/workflow_email.py†L296-L320】【F:backend/workflows/groups/negotiation_close.py†L25-L66】【F:backend/workflows/groups/negotiation_close.py†L467-L489】

**Regression Guard:** With `negotiation_pending_decision` present, any client reply should only see the waiting note; the offer should not reappear and only one HIL task should exist.

**Playbook:** If a client acceptance seems ignored, check `hil_open` and `current_step`—they should be `True` and `5`. If not, re-run intake on the acceptance email; the new heuristic forces the HIL acceptance path with the offer summary attached.

### Billing address required before offer submission (New)
**Symptoms:** Clients could confirm offers without a billing address; the manager/HIL view sometimes lacked billing context alongside the line items.

**Fixes Applied:**
1. Offer drafts and HIL summaries now include the billing address (formatted leniently) plus all line items so the manager sees the full offer payload.【F:backend/workflows/groups/offer/trigger/process.py†L200-L260】【F:backend/workflows/groups/negotiation_close.py†L430-L520】
2. Acceptance in Steps 4–5 is gated on a complete billing address (name/company, street, postal code, city, country). If a client confirms before sharing it, we prompt for the missing pieces, keep the thread on “Awaiting Client,” and auto-submit the offer for HIL as soon as the address is provided—no second confirmation needed.【F:backend/workflows/groups/offer/trigger/process.py†L70-L140】【F:backend/workflows/groups/negotiation_close.py†L85-L190】

**UX:** When billing is missing, the assistant politely lists the missing fields and waits; once the address is captured, the offer confirmation resumes automatically and the HIL view includes the full billing line.

**Regression watchouts (Nov 25):**
- Address fragments (e.g., “Postal code: 8000; Country: Switzerland”) are now treated as billing updates on an existing event, so we stay on Step 4/5 instead of manual review. Room-choice replies stay room choices; we no longer overwrite billing with room labels, and we only display billing once at least some required fields are present.【F:backend/workflows/groups/intake/trigger/process.py†L600-L666】【F:backend/workflows/groups/offer/trigger/process.py†L60-L120】【F:backend/workflows/groups/negotiation_close.py†L70-L140】
- Billing prompts now include a concrete example (“Helvetia Labs, Bahnhofstrasse 1, 8001 Zurich, Switzerland”). Partial replies won’t duplicate room prompts or trigger manual review detours.【F:backend/workflows/groups/offer/trigger/process.py†L130-L190】【F:backend/workflows/groups/intake/trigger/process.py†L610-L666】

**Pending risk:** Empty or single-word replies still won’t capture billing; real-world replies should include at least one of street/postal/city/country.

### Room choice repeats / manual-review detours (Ongoing Fix)
**Symptoms:** After a client types a room name (e.g., “Room E”), the workflow dropped back to Step 3, showed another room list, or enqueued manual review; sometimes the room label was mistaken for a billing address (“Billing Address: Room E”).

**Fixes Applied:**
- Early room-choice detection now runs for any confidence level and locks the room at Step 4 (thread stays “Awaiting Client”) instead of rerunning Step 3.【F:backend/workflows/groups/intake/trigger/process.py†L120-L155】【F:backend/workflows/groups/intake/trigger/process.py†L760-L815】
- Billing updates while awaiting address only trigger when the reply looks like an address; “Room …” or other short replies no longer overwrite billing or send to manual review.【F:backend/workflows/groups/intake/trigger/process.py†L650-L676】

**Regression Guard:** After a client types a room name, the next message should be the Step 4 offer/products prompt (no duplicate room list, no manual-review task, no “Billing Address: Room …”). If confidence is low, the room should still be accepted.

### Manager approval now opt-in (New)
**Symptoms:** Offers were sent to HIL/manager even when the client didn’t ask for manager review.

**Fixes Applied:** Acceptance now only opens HIL when the client explicitly mentions the manager; otherwise the offer is confirmed directly and we continue to site-visit prep.【F:backend/workflows/groups/offer/trigger/process.py†L180-L250】【F:backend/workflows/groups/offer/trigger/process.py†L1190-L1245】

**Regression Guard:** A plain “that’s fine” acceptance now always opens the manager approval task (Step 5) so the manager sees the approve/decline buttons in the UI before the client-facing confirmation is released. GUI Approve/Reject calls `/api/tasks/{task_id}/approve|reject`, which applies the pending Step‑5 decision and sends the assistant reply; if it doesn’t fire, check that the task is `offer_message` (not room/date/manual) and that `pending_hil_requests` contains only step=5 entries.【F:backend/main.py†L760-L860】【F:backend/workflow_email.py†L422-L540】

### Menu selection alongside room choice (New)
**Symptoms:** When a client replies “Room E with Seasonal Garden Trio,” the menu wasn’t captured, menus weren’t shown with room options, and the offer totals ignored catering.

**Fixes Applied:**
- Menu choices are detected in the room-selection turn; we add the menu as a catering line item (per-event by default) and store the choice.【F:backend/workflows/groups/intake/trigger/process.py†L150-L190】
- Room-availability messages now surface concise menu bullets with per-event pricing (rooms: all) so the client can decide in one go.【F:backend/workflows/groups/room_availability/trigger/process.py†L980-L1030】
- Offer/HIL summaries respect manager opt-in and keep CTA text aligned (confirm vs manager approval).【F:backend/workflows/groups/offer/trigger/process.py†L1000-L1105】【F:backend/workflows/groups/negotiation_close.py†L570-L610】
- If no menu was chosen before the offer, the offer body includes a short “Menu options you can add” block; when a menu was already selected, the list is omitted to avoid repetition.【F:backend/workflows/groups/offer/trigger/process.py†L1065-L1115】
- Coffee badges in room cards are suppressed unless the client asked for coffee/tea/drinks, so unrelated “Coffee ✓” no longer appears by default.【F:backend/workflows/groups/room_availability/trigger/process.py†L900-L960】
- The “Great — <room> … ready for review” intro is now only shown when the client explicitly asked for manager review; normal confirmations start directly with the offer draft line.【F:backend/workflows/groups/offer/trigger/process.py†L1000-L1010】

**Regression Guard:** A reply like “Room B with Seasonal Garden Trio” should lock the room, add the menu (priced per guest) to the offer, and show a confirmation CTA without defaulting to manager approval.
