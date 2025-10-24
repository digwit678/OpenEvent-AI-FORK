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
- **Exits:** Returns to caller if invoked from a detour, otherwise advances to Step 3 with in-progress thread state and an approval-ready confirmation draft.【F:backend/workflows/groups/date_confirmation/trigger/process.py†L125-L159】

### Step 3 — Room Availability & HIL Gate
- **Entry guard:** Requires a chosen date; otherwise detours to Step 2 and records caller provenance.【F:backend/workflows/groups/room_availability/trigger/process.py†L51-L121】
- **Actions:** Re-evaluate inventory when requirements change, select the best room, draft outcome messaging, compute alternatives, and store a `room_pending_decision` payload awaiting HIL approval.【F:backend/workflows/groups/room_availability/trigger/process.py†L60-L115】
- **HIL gate:** When `hil_approve_step==3`, managers approve or reject the pending room before progressing; approval locks the room, aligns `room_eval_hash`, and advances to Step 4.【F:backend/workflows/groups/room_availability/trigger/process.py†L246-L315】
- **Caching:** If the locked room and requirement hash already match, Step 3 short-circuits and returns control to the caller without recomputing availability.【F:backend/workflows/groups/room_availability/trigger/process.py†L60-L205】

### Step 4 — Offer Preparation
- **Entry guard:** Requires an event entry populated by prior steps; otherwise halts with `offer_missing_event`.【F:backend/workflows/groups/offer/trigger/process.py†L21-L33】
- **Actions:** Normalize product operations, rebuild pricing inputs, call `ComposeOffer` to generate totals, version offers, and queue a draft email for approval.【F:backend/workflows/groups/offer/trigger/process.py†L39-L93】【F:backend/workflows/groups/offer/trigger/process.py†L154-L233】
- **State updates:** Resets negotiation counters when returning from Step 5, sets `transition_ready=False`, and moves to Step 5 while clearing `caller_step`.【F:backend/workflows/groups/offer/trigger/process.py†L59-L92】

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
| “Please confirm the booking” | Confirmation draft queued; awaits HIL sign-off | Deposit/site-visit logic handled before final send.【F:backend/workflows/groups/event_confirmation/trigger/process.py†L75-L318】 |
| “Deposit has been paid” | Deposit marked paid, confirmation draft regenerated | Ensures status before final confirmation.【F:backend/workflows/groups/event_confirmation/trigger/process.py†L175-L238】 |

