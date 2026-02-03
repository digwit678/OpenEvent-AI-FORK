# Plan: Email Inbox Workflow Threading (Frontend Integration Prep)

**Status:** Draft  
**Owner:** OpenEvent AI  
**Last Updated:** 2026-02-03

## Problem Statement
We need a robust, low-error way to attach inbound emails to the correct workflow thread (event session) in the classic email inbox. Direct replies are easy, but two confusing cases must be handled safely:
1. A client starts a **new email** (not a reply) that still belongs to the **same event**.
2. A client writes **months later** for a **new event**, and the system must **not** attach it to the old thread.

The solution must be **LLM-first**, avoid keyword-driven misclassification, and **never** falsely assign messages to the wrong event. Every message must be assigned either to the correct existing thread or to a **new thread** (if the event is new or ambiguous).

---

## Goals
- **Zero false assignment**: Only attach to an existing event when confidence is high.
- **LLM-first semantics**: Avoid keyword-only detection for thread assignment.
- **Seamless for inbox UX**: Thread mapping should “just work” for frontend once integrated.
- **Cost-aware**: Minimize additional LLM calls by reusing existing unified detection.

## Non-Goals
- Frontend integration work (UI, inbox wiring) is **not** implemented in this plan.
- No changes to email provider integration (Gmail/Outlook/etc.) in this phase.

---

## Proposed Architecture

### 1) Data Model Additions (Backend)
**Email Message Metadata**
- `message_id`, `in_reply_to`, `references`
- `subject_normalized`, `from_address`, `to_address`, `sent_at`
- `thread_id` (internal), `event_id` (workflow session)

**Event Signature (per event)**
Structured, LLM-derived summary used for matching:
- `date_range` (start/end or preferred windows)
- `time_range`
- `room_or_location`
- `participant_count`
- `budget` (if known)
- `event_type` (if known)
- `last_updated_from_message_id`

**Thread Mapping**
`email_thread_id → event_id` mapping plus history of merged/split decisions.

---

### 2) Thread Resolver Pipeline (LLM-first, deterministic-safe)
The resolver produces a **single decision** for each message: `attach_to_event_id` or `create_new_event`.

**Step A — Deterministic Linking (No LLM)**
1. **Reply headers**: if `In-Reply-To` or `References` matches a known `message_id`, attach to that thread.
2. **Explicit event token** (optional, non-keyword): if a structured event token/header exists (e.g., `X-OpenEvent-Thread` or footer token), attach deterministically.

**Step B — Candidate Selection**
- If no deterministic link:
  - Build candidate set: **active events** + **recently closed events** for the client.
  - Limit candidates (e.g., last N by activity) to reduce LLM cost.

**Step C — Semantic Match (LLM)**
- Reuse existing unified detection output where possible to extract a **Message Signature** (date/time/room/participants).
- LLM compares **Message Signature + message summary** against each **Event Signature**.
- Output schema: `{decision: event_id | new_event | uncertain, confidence, reasons}`

**Step D — Hard Constraints Check**
Reject attachment if:
- Dates conflict (message specifies date far outside event date range)
- Event is completed/cancelled and message is a clear new request
- Room/location mismatch with high confidence

**Step E — Final Decision**
- **Attach only if** confidence ≥ threshold **and** constraints pass.
- Otherwise **create new event** and tag `possible_duplicate_event_ids` for manual merge.

---

### 3) “Foolproof” Safeguards (Zero False Assignment)
- **Conservative attachment**: attach only when LLM + constraints agree.
- **Ambiguity → new thread**: avoid wrong linking even if it creates duplicates.
- **Optional clarification**: if uncertainty is high, auto-draft a clarification question (“Is this about your [date] booking or a new event?”).
- **Audit trail**: store decision inputs + LLM rationale for review/debugging.

---

## How the Two Confusing Cases Are Handled

### Case 1 — New email, same event
- No reply headers → candidate selection picks recent active event.
- LLM sees same date/time/room/participants → **attach with high confidence**.
- If ambiguous, new thread created + merge suggestion.

### Case 2 — New email months later, different event
- Event is closed/dated in the past.
- Message signature shows a new future date or new request → **new event**.
- Only attach to old event if LLM explicitly classifies as follow-up (invoice/feedback).

---

## Implementation Steps (Backend + Shared Logic)
1. **Add storage for email metadata + event signatures** (DB or JSON store).
2. **Create `thread_resolver` module** with the pipeline above.
3. **Integrate resolver** at the inbound email entrypoint before workflow routing.
4. **Persist decision + audit log** for debugging and manual review.
5. **Add merge hooks** (backend-only) to allow future UI to merge threads safely.

---

## Testing Plan
- **Unit tests** for deterministic header linking and explicit token linking.
- **Semantic match tests** with mocked LLM outputs:
  - Same event, no reply headers → attaches correctly.
  - New event months later → creates new thread.
  - Multiple concurrent events → attaches only with high confidence.
  - Ambiguous case → new thread + merge suggestion.
- **Regression fixtures** for previously known keyword-misclassification issues.

---

## Integration-Time Tasks
These will be documented in **`docs/integration/`** when frontend integration is scheduled (not part of this plan):
- Inbox UI wiring to show one workflow thread per email thread
- Merge/split controls for managers
- Surfacing resolver confidence + rationale in UI

---

## Open Questions
- Default time window for “recently closed” events (30/60/90 days?)
- Whether to include a hidden event token in email footers for deterministic linking
- LLM confidence threshold tuning (needs offline eval set)
