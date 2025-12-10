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

## HIL Toggle System (AI Reply Approval)

**Last Updated:** 2025-12-10

The system supports two tiers of Human-in-the-Loop (HIL) approval for client-facing messages:

### Two-Tier HIL Architecture

| Tier | Task Type | When Created | Purpose |
|------|-----------|--------------|---------|
| **1. Step-Specific HIL** | `date_confirmation_message`, `room_availability_message`, `offer_message`, `special_request`, `too_many_attempts` | **ALWAYS** (via `_enqueue_hil_tasks`) | Original workflow gates: offer confirmation, special manager requests, >3 failed attempts |
| **2. AI Reply Approval** | `ai_reply_approval` | **ONLY when `OE_HIL_ALL_LLM_REPLIES=true`** | NEW optional gate: approve ALL AI-generated messages before sending |

### Environment Variable

```bash
# Enable AI reply approval for all messages (Tier 2)
export OE_HIL_ALL_LLM_REPLIES=true

# Disable (default) - only step-specific HIL gates active (Tier 1)
unset OE_HIL_ALL_LLM_REPLIES
```

### Important Distinction

**Toggle OFF** (`OE_HIL_ALL_LLM_REPLIES` unset/false):
- AI messages go directly to clients (no extra approval step)
- Step-specific HIL tasks STILL work (offer confirmation, special requests, too many attempts)
- This is the **original behavior** - nothing new

**Toggle ON** (`OE_HIL_ALL_LLM_REPLIES=true`):
- EVERY AI-generated message goes to manager approval queue first
- Step-specific HIL tasks ALSO work (both tiers active)
- Adds an EXTRA approval layer on top of existing workflow

### Frontend UI

| Section | Color | Visibility |
|---------|-------|------------|
| Manager AI Reply Approval | Green | Only when `OE_HIL_ALL_LLM_REPLIES=true` |
| Client HIL Tasks (step-specific) | Purple | Always (when tasks exist) |

### Key Code Paths

| Logic | Location |
|-------|----------|
| Step-specific task creation | `backend/workflow_email.py:_enqueue_hil_tasks()` — ALWAYS runs |
| AI reply approval task creation | `backend/workflow_email.py:1130-1188` — only when toggle ON |
| Task deduplication | Checks for existing PENDING `ai_reply_approval` task for same thread |

### Common Gotcha

Never skip `_enqueue_hil_tasks()` when the AI reply toggle is ON. Both task creation paths must run independently:
1. `_enqueue_hil_tasks()` for step-specific HIL tasks (always)
2. `ai_reply_approval` task creation for the toggle (when enabled)

---

## Agent Tools Layer (AGENT_MODE=openai)

When `AGENT_MODE=openai` is set, the system uses OpenAI function-calling for tool execution instead of the deterministic workflow. Tools are bounded per step to enforce the same workflow constraints as the deterministic path.

### Tool Allowlist by Step

| Step | Allowed Tools |
| --- | --- |
| 2 – Date | `tool_suggest_dates`, `tool_parse_date_intent` |
| 3 – Room | `tool_room_status_on_date`, `tool_capacity_check`, `tool_evaluate_rooms` |
| 4 – Offer | `tool_build_offer_draft`, `tool_persist_offer`, `tool_list_products`, `tool_list_catering`, `tool_add_product_to_offer`, `tool_remove_product_from_offer`, `tool_send_offer` |
| 5 – Negotiation | `tool_negotiate_offer`, `tool_transition_sync` |
| 7 – Confirmation | `tool_follow_up_suggest`, `tool_classify_confirmation` |

### Key Files

| File | Description |
| --- | --- |
| `backend/agents/chatkit_runner.py` | `ENGINE_TOOL_ALLOWLIST`, `TOOL_DEFINITIONS`, `execute_tool_call`, schema validation |
| `backend/agents/tools/dates.py` | Date suggestion and parsing tools |
| `backend/agents/tools/rooms.py` | Room status and capacity tools |
| `backend/agents/tools/offer.py` | Offer composition, products, and catering tools |
| `backend/agents/tools/negotiation.py` | Negotiation handling |
| `backend/agents/tools/transition.py` | Transition sync |
| `backend/agents/tools/confirmation.py` | Confirmation classification |

### Testing

```bash
# Run all agent tools tests (parity + approve path)
pytest backend/tests/agents/ -m "" -v

# Run parity tests only
pytest backend/tests/agents/test_agent_tools_parity.py -m "" -v

# Run approve path tests only
pytest backend/tests/agents/test_manager_approve_path.py -m "" -v
```

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

### Step 2 Date Confirmation Unconditionally Requiring HIL (Fixed)
**Symptoms:** Every date option message in Step 2 went to HIL for manager approval, even when the client hadn't reached 3 failed attempts. All date confirmation drafts showed up in the manager panel regardless of escalation status.

**Root Cause:** In commit b59100ce (Nov 17, 2025 - "enforce hybrid Q&A + gatekeeping confirmations"), the code added HIL escalation logic for Step 2 after 3 failed attempts. However, line 1595 was set to `requires_approval = True` unconditionally, while the thread_state was correctly conditional on `escalate_to_hil`. This mismatch meant all date drafts had `requires_approval=True` even when not escalating.

**Fix Applied:**
Changed `draft_message["requires_approval"] = True` to `draft_message["requires_approval"] = escalate_to_hil` so that only escalation cases (≥3 attempts) route to HIL.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L1595-L1597】

**Regression Guard:** Step 2 date options should go directly to the client (no HIL task created) unless `date_proposal_attempts >= 3`. If you see a Step-2 date task in the manager panel before 3 attempts, check that `requires_approval` is tied to `escalate_to_hil`.

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

**Regression Guard:** A reply like "Room B with Seasonal Garden Trio" should lock the room, add the menu (priced per guest) to the offer, and show a confirmation CTA without defaulting to manager approval.

### Room selections misread as acceptances (New)
**Symptoms:** When clients clicked/typed room-action labels such as "Proceed with Room E", Step 4 treated the message as an offer acceptance, sent the thread to HIL, and blocked normal offer iteration.

**Fix:** Offer acceptance now ignores messages that include a detected room choice (`_room_choice_detected`) or the phrase "proceed with room…", so these stay in the normal offer loop instead of triggering manager review.【F:backend/workflows/groups/offer/trigger/process.py†L185-L204】

**Regression Guard:** Room selections should keep the thread in "Awaiting Client" with `action=offer_draft_prepared` and no pending HIL requests unless the client explicitly accepts the offer.

---

### Date Change Detours from Steps 3/4/5 (Fixed - 2025-12-03)
**Symptoms:** When a client at Step 3 (Room Availability), Step 4 (Offer), or Step 5 (Negotiation) requested a date change (e.g., "sorry made a mistake, wanted 2026-02-28 instead"), the workflow would:
- Return generic fallback message "Thanks for the update. I'll keep you posted..."
- Not route back to Step 2 to confirm the new date
- In some cases, enter an infinite detour loop with no proper response

**Root Causes:**
1. **Step 5 - No message text parsing:** `_detect_structural_change()` only checked `state.user_info.get("date")` but this field wasn't populated because the LLM extraction skipped it (event_date already had a value).
2. **Step 3 - Duplicate detour loop:** When Step 2's `finalize_confirmation` internally called Step 3, Step 3 would detect the same message as a date change again (pattern-based detection) and try to detour back to Step 2, creating an infinite loop.
3. **Step 3 - Multi-date parsing bug:** The skip-duplicate-detour logic checked only `message_dates[0]` which could be today's date (parsed erroneously), causing the skip to fail.

**Fixes Applied:**
1. **Step 5:** Updated `_detect_structural_change()` to parse dates directly from message text using `parse_all_dates()`. If any date differs from `chosen_date`, triggers detour to Step 2.【F:backend/workflows/groups/negotiation_close.py†L532-L558】
2. **Step 3:** Added skip-duplicate-detour check that compares message dates with `chosen_date`. If the just-confirmed date is in the message, it's not a new change request.【F:backend/workflows/groups/room_availability/trigger/process.py†L197-L223】
3. **Step 3:** Changed date matching from `message_dates[0] == chosen_date` to `chosen_date in message_dates` to handle cases where multiple dates are parsed.

**Regression Guard:** After a client at any step (3/4/5) says "sorry, I meant [new date]", the workflow should:
- Detect the date change
- Route back to Step 2 to confirm the new date
- Re-evaluate room availability for the new date
- Return to the caller step (or proceed forward)

### Date Mismatch: Feb 7 becomes Feb 20 (Open - Investigating)
**Symptoms:** Client confirms "2026-02-07 18:00–22:00" in Step 2, but Step 3 room availability message shows "Rooms for 30 people on 20.02.2026" instead of 07.02.2026.

**Observed:**
- Client input: "2026-02-07 18:00–22:00"
- System output: "Rooms for 30 people on 20.02.2026" and "Room B on None" in offer title
- Three separate issues: wrong day (7 → 20), wrong format in some places, "None" appearing in offer title

**Suspected Cause:** Date parsing or storage corruption somewhere in the Step 2 → Step 3 transition. Possibly:
1. Date extraction parsing error (confusing day/month)
2. DD.MM.YYYY vs YYYY-MM-DD format conversion issue
3. `chosen_date` getting corrupted during step transition

**Files to investigate:**
- `backend/workflows/groups/date_confirmation/trigger/process.py` - date parsing and storage
- `backend/workflows/common/datetime_parse.py` - date format conversions
- `backend/workflows/groups/room_availability/trigger/process.py` - date retrieval for room search

**Reproduction:** Start new event → provide dates in February → confirm "2026-02-07" → check if Step 3 shows correct date.

---

## Test Suite Status

**Last Updated:** 2025-11-27

### Inventory Completed

A comprehensive test suite inventory was performed. See:
- `tests/TEST_INVENTORY.md` — Full listing of all test files with coverage, type, and status
- `tests/TEST_REORG_PLAN.md` — Proposed reorganization and migration actions

### Current State

| Location | Tests | Status |
|----------|-------|--------|
| `tests/specs/` | ~90 | 68 pass, 22 fail |
| `tests/workflows/` | ~75 | 67 pass, 8 fail |
| `tests/gatekeeping/` | 3 | all pass |
| `tests/flows/` | 10 | 5 pass, 5 fail |
| `tests/e2e_v4/` | 2 | all pass |
| `tests/_legacy/` | ~20 | xfail (v3 reference) |
| `backend/tests/smoke/` | 1 | pass |
| `backend/tests_integration/` | 4 | requires live env |

### Legacy Tests

Legacy v3 workflow tests are isolated in `tests/_legacy/` with:
- `pytest.mark.legacy` marker
- `xfail` expectation (retained for regression reference)
- No changes made; these are not run by default

### Failing Tests Requiring Attention

**Priority 1 — Change Propagation (Core v4)**
- `tests/specs/dag/test_change_propagation.py` (4 failures)
- `tests/specs/dag/test_change_scenarios_e2e.py` (5 failures)
- `tests/specs/dag/test_change_integration_e2e.py` (4 failures)

These test the v4 DAG-based change routing. The API may have evolved; expectations need alignment.

**Priority 2 — General Q&A Path**
- `tests/specs/date/test_general_room_qna_*.py` (7 failures)
- `tests/flows/test_flow_specs.py` (5 failures)

Q&A path expectations appear outdated; fixtures need update.

**Priority 3 — Minor**
- `tests/workflows/test_offer_product_operations.py` (1 failure) — quantity update logic
- `tests/workflows/qna/test_verbalizer.py` (1 failure) — fallback format
- `tests/workflows/date/test_confirmation_window_recovery.py` (1 failure) — relative date edge case

### Next Steps

1. **Fix change propagation tests** — These cover core v4 functionality (date/room/requirements detours)
2. **Update Q&A test expectations** — Align with current behavior
3. **Add missing coverage** — Steps 5-7 have limited unit tests
4. **Consolidate structure** — Consider merging `tests/workflows/` into `tests/specs/` per reorganization plan

### Running Tests

```bash
# Activate environment
source scripts/oe_env.sh

# Run default v4 tests
pytest

# Run backend smoke test
pytest backend/tests/smoke/ -m ""

# Run with verbose output
pytest tests/specs/ -v --tb=short

# Run new detection/flow tests
pytest backend/tests/detection/ backend/tests/regression/ backend/tests/flow/ -m "" -v
```

---

## Detection & Flow Tests (New)

**Last Updated:** 2025-11-27

A comprehensive detection test suite was created to cover:
- Q&A detection
- Manager request detection
- Acceptance/confirmation detection
- Detour change propagation
- Shortcut capture
- Gatekeeping (billing + deposit)
- Happy-path flow Steps 1–4
- Regression tests linked to TEAM_GUIDE bugs

See `tests/TEST_MATRIX_detection_and_flow.md` for full test ID matrix.

### Test Locations

| Category | Location | Tests |
|----------|----------|-------|
| Q&A Detection | `backend/tests/detection/test_qna_detection.py` | DET_QNA_001–006 |
| Manager Request | `backend/tests/detection/test_manager_request.py` | DET_MGR_001–006 |
| Acceptance | `backend/tests/detection/test_acceptance.py` | DET_ACCEPT_001–009 |
| Detour Changes | `backend/tests/detection/test_detour_changes.py` | DET_DETOUR_* |
| Shortcuts | `backend/tests/detection/test_shortcuts.py` | DET_SHORT_001–006 |
| Gatekeeping | `backend/tests/detection/test_gatekeeping.py` | DET_GATE_BILL_*, DET_GATE_DEP_* |
| Happy Path Flow | `backend/tests/flow/test_happy_path_step1_to_4.py` | FLOW_1TO4_HAPPY_001 |
| Regression | `backend/tests/regression/test_team_guide_bugs.py` | REG_* |

### Test Results Summary

**Run Date:** 2025-11-27
**Results:** 161 passed, 0 failed

All detection and flow tests pass after the following fixes:

### Detection Logic Fixes (2025-11-27)

1. **Manager Request Detection — "real person" variant (DET_MGR_002)**
   - **Issue:** The phrase "I'd like to speak with a real person" wasn't caught by `_looks_like_manager_request`.
   - **Fix:** Added regex pattern `r"\b(speak|talk|chat)\s+(to|with)\s+(a\s+)?real\s+person\b"` to `_MANAGER_PATTERNS` in `backend/llm/intent_classifier.py:229`.
   - **Test:** `test_DET_MGR_002_real_person` now passes.

2. **Q&A Detection — Parking Policy (DET_QNA_006)**
   - **Issue:** The `parking_policy` Q&A type existed but its keywords didn't match "where can guests park?".
   - **Fix:** Added `" park"` (with leading space) and `"park?"` to the `parking_policy` keywords in `backend/llm/intent_classifier.py:157-158`.
   - **Test:** `test_DET_QNA_006_parking_question` now passes.

### Regression Tests Linked to TEAM_GUIDE Bugs

| Test ID | TEAM_GUIDE Bug | Status |
|---------|----------------|--------|
| `REG_PRODUCT_DUP_001` | Product Additions Causing Duplicates | ✓ Pass |
| `REG_ACCEPT_STUCK_001` | Offer Acceptance Stuck / Not Reaching HIL | ✓ Pass |
| `REG_HIL_DUP_001` | Duplicate HIL sends after offer acceptance | ✓ Pass |
| `REG_DATE_MONTH_001` | Spurious unavailable-date apologies | ✓ Pass |
| `REG_QUOTE_CONF_001` | Quoted confirmation triggering Q&A | ✓ Pass |
| `REG_ROOM_REPEAT_001` | Room choice repeats / manual-review detours | ✓ Pass |
| `REG_BILL_ROOM_001` | Room label as billing address | ✓ Pass |

### Anti-Fallback Assertions

All tests include guards against legacy fallback messages:
```python
FALLBACK_PATTERNS = [
    "no specific information available",
    "sorry, cannot handle",
    "unable to process",
    "i don't understand",
    "there appears to be no",
    "it appears there is no",
]
```

If any test response contains these patterns, it fails with `FALLBACK DETECTED`.

### Running Detection Tests

```bash
# Run all detection/flow tests (bypasses pytest.ini markers)
pytest backend/tests/detection/ backend/tests/regression/ backend/tests/flow/ -m "" -v

# Run specific category
pytest backend/tests/detection/test_acceptance.py -m "" -v

# Run regression tests only
pytest backend/tests/regression/ -m "" -v
```

---

## Safety Sandwich Pattern (LLM Verbalizer)

**Last Updated:** 2025-11-27

The Safety Sandwich pattern provides LLM-powered verbalization of room and offer messages while ensuring all hard facts (dates, prices, room names, participant counts) are preserved.

### Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    Safety Sandwich Flow                          │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│   Deterministic Engine ─┐                                        │
│   (builds facts bundle) │                                        │
│                         ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  RoomOfferFacts                                          │   │
│   │  - event_date (DD.MM.YYYY)                              │   │
│   │  - participants_count                                    │   │
│   │  - rooms: [{name, status, capacity}]                    │   │
│   │  - menus: [{name, price}]                               │   │
│   │  - total_amount, deposit_amount                         │   │
│   └─────────────────────────────────────────────────────────┘   │
│                         │                                        │
│                         ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  LLM Verbalizer (verbalize_room_offer)                  │   │
│   │  - Rewords for empathetic, professional tone            │   │
│   │  - CANNOT alter dates, prices, room names               │   │
│   └─────────────────────────────────────────────────────────┘   │
│                         │                                        │
│                         ▼                                        │
│   ┌─────────────────────────────────────────────────────────┐   │
│   │  Deterministic Verifier (verify_output)                 │   │
│   │  - Extracts hard facts from LLM output                  │   │
│   │  - Checks: all canonical facts present?                 │   │
│   │  - Checks: any facts invented?                          │   │
│   │  - Returns: VerificationResult(ok, missing, invented)   │   │
│   └─────────────────────────────────────────────────────────┘   │
│                         │                                        │
│            ┌────────────┴────────────┐                          │
│            │                         │                          │
│       ok=True                   ok=False                        │
│            │                         │                          │
│            ▼                         ▼                          │
│   Return LLM text            Return fallback text               │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
```

### Key Files

| File | Purpose |
|------|---------|
| `backend/ux/verbalizer_payloads.py` | Facts bundle types (RoomFact, MenuFact, RoomOfferFacts) |
| `backend/ux/verbalizer_safety.py` | Deterministic verifier (extract_hard_facts, verify_output) |
| `backend/ux/safety_sandwich_wiring.py` | Workflow integration helpers |
| `backend/llm/verbalizer_agent.py` | LLM entry point (verbalize_room_offer) |

### Hard Facts (Must Be Preserved)

The verifier extracts and checks these fact types:

| Fact Type | Pattern | Example |
|-----------|---------|---------|
| Dates | `DD.MM.YYYY` | `15.03.2025` |
| Currency | `CHF X` or `CHF X.XX` | `CHF 500`, `CHF 92.50` |
| Room names | Case-insensitive match | `Room A`, `Punkt.Null` |
| Participant counts | Integer in "X participants" context | `30 participants` |
| Time strings | `HH:MM` or `HH:MM–HH:MM` | `14:00–18:00` |

### Verification Rules

1. **Missing Facts:** Every hard fact in the facts bundle MUST appear in LLM output
2. **Invented Facts:** LLM output MUST NOT contain dates/prices not in the bundle
3. **Order Preservation:** Section headers must appear in original order (if applicable)

### Tone Control

The verbalizer respects environment variables:

```bash
# Force plain (deterministic) tone
VERBALIZER_TONE=plain

# Enable empathetic LLM tone
VERBALIZER_TONE=empathetic
# or
EMPATHETIC_VERBALIZER=1
```

Default is `plain` (no LLM, deterministic text only).

### Workflow Integration Points

The Safety Sandwich is wired into:

1. **Step 3 (Room Availability):** `backend/workflows/groups/room_availability/trigger/process.py:412-421`
2. **Step 4 (Offer):** `backend/workflows/groups/offer/trigger/process.py:280-290`

### Tests

```bash
# Run Safety Sandwich tests
pytest backend/tests/verbalizer/ -m "" -v

# Test breakdown:
# - test_safety_sandwich_room_offer.py: 19 tests (facts extraction, verification)
# - test_safety_sandwich_wiring.py: 10 tests (workflow helpers)
```

### Test IDs

| Test ID | Description |
|---------|-------------|
| TEST_SANDWICH_001 | Happy path - valid paraphrase accepted |
| TEST_SANDWICH_002 | Changed price rejected |
| TEST_SANDWICH_003 | Invented date rejected |
| TEST_SANDWICH_004 | WorkflowState integration |
| TEST_SANDWICH_005 | Edge cases (empty, no rooms) |
| TEST_SANDWICH_006 | Hard facts extraction |

---

## Universal Verbalizer (Human-Like UX)

**Last Updated:** 2025-11-27

The Universal Verbalizer transforms ALL client-facing messages into warm, human-like communication that helps clients make decisions easily.

### Design Principles

1. **Sound like a helpful human** - Conversational language, not robotic bullet points
2. **Help clients decide** - Highlight best options with clear reasons, don't just list data
3. **Be concise but complete** - Every fact preserved, wrapped in helpful context
4. **Show empathy** - Acknowledge the client's needs and situation
5. **Guide next steps** - Make it clear what happens next

### Message Transformation Example

**BEFORE (data dump):**
```
Room A - Available - Capacity 50 - Coffee: ✓ - Projector: ✓
Room B - Option - Capacity 80 - Coffee: ✓ - Projector: ✗
```

**AFTER (human-like):**
```
Great news! Room A is available for your event on 15.03.2025 and fits your
30 guests perfectly. It has everything you asked for — the coffee service
and projector are both included.

If you'd like more space, Room B (capacity 80) is also open, though we'd
need to arrange the projector separately. I'd recommend Room A as your
best match.

Just let me know which you prefer, and I'll lock it in for you.
```

### Integration Points

The Universal Verbalizer is integrated at two levels:

1. **`append_footer()`** - Automatically verbalizes body before adding footer
2. **`verbalize_draft_body()`** - Explicit verbalization for messages without footer

### Key Files

| File | Purpose |
|------|---------|
| `backend/ux/universal_verbalizer.py` | Core verbalizer with UX-focused prompts |
| `backend/workflows/common/prompts.py` | Integration helpers (`append_footer`, `verbalize_draft_body`) |

### Tone Control

**Default is now `empathetic`** for human-like UX.

```bash
# Disable verbalization (use deterministic text only)
VERBALIZER_TONE=plain
# or
PLAIN_VERBALIZER=1

# Explicitly enable (this is now the default)
VERBALIZER_TONE=empathetic
```

For CI/testing, set `VERBALIZER_TONE=plain` to get deterministic output.

### Step-Specific Guidance

The verbalizer uses context-aware prompts for each workflow step:

| Step | Focus |
|------|-------|
| Step 2 (Date) | Help client choose confidently, highlight best-fit dates |
| Step 3 (Room) | Lead with recommendation, explain differences clearly |
| Step 4 (Offer) | Make value clear, justify totals, easy to accept |
| Step 5 (Negotiation) | Acknowledge decisions warmly, maintain momentum |
| Step 7 (Confirmation) | Celebrate their choice, make admin feel easy |

### Hard Rules (Never Broken)

Even in empathetic mode, these facts are ALWAYS preserved exactly:

- Dates (DD.MM.YYYY format)
- Prices (CHF X.XX format)
- Room names (case-insensitive match)
- Participant counts
- Time windows

If the LLM output fails verification, the system falls back to deterministic text.
