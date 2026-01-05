# OpenEvent Workflow Team Guide

## Quick Start: API Key Setup

Before running the project, configure API keys using macOS Keychain:

```bash
# OpenAI (for verbalization)
security add-generic-password -s 'openevent-api-test-key' -a "$USER" -w 'YOUR-OPENAI-KEY'

# Gemini (for intent/entity extraction)
security add-generic-password -s 'openevent-gemini-key' -a "$USER" -w 'YOUR-GOOGLE-KEY'

# Start server (auto-loads keys from Keychain)
./scripts/dev/dev_server.sh
```

See [SETUP_API_KEYS.md](./SETUP_API_KEYS.md) for full guide.

---

## Production Readiness Risks (Audit 2026-01-05)

- Auth is disabled by default; set AUTH_ENABLED=1 in production or all endpoints are public.
- ENV defaults to dev; set ENV=prod to avoid exposing debug/test routes and debug traces.
- LLM input sanitization is not wired into unified detection/Q&A/verbalizer entrypoints yet.
- Rate limiting middleware import exists in backend/main.py but the module is missing in this repo.
- Mock deposit payment endpoint should be gated or disabled in production.

---

## UX Design Principle: Verbalization vs Info Page

**CRITICAL DESIGN RULE - Always remember when working on verbalization:**

| Channel | Purpose | Content Style |
|---------|---------|---------------|
| **Chat/Email (verbalization)** | Direct user feedback | Clear, conversational, NOT overloaded. No tables, no dense data. |
| **Info Page/Links** | Detailed exploration | Tables, comparisons, full menus, room details for those who want depth. |

**Implementation:**
- Chat messages use conversational prose: "I found 3 options that work for you."
- Detailed data goes into `table_blocks` structure for frontend to render in info section
- Always include info links for users who want more detail
- Never put markdown tables directly in chat/email body text

**Why:** Keeps emails scannable and professional while still providing complete info for those who want it.

---

## Overview
- **Actors & responsibilities**
  - *Trigger nodes* (purple) parse incoming client messages and orchestrate state transitions for each workflow group.【F:backend/workflows/steps/step1_intake/trigger/process.py†L30-L207】【F:backend/workflow_email.py†L86-L145】
  - *LLM nodes* (green/orange) classify intent, extract structured details, and draft contextual replies while keeping deterministic inputs such as product lists and pricing stable.【F:backend/workflows/steps/step1_intake/llm/analysis.py†L10-L20】【F:backend/workflows/steps/step4_offer/trigger/process.py†L39-L93】
  - *OpenEvent Actions / HIL gates* (light-blue) capture manager approvals, enqueue manual reviews, and persist audited decisions before messages can be released to clients.【F:backend/workflows/steps/step3_room_availability/trigger/process.py†L246-L316】【F:backend/workflows/steps/step4_offer/trigger/process.py†L46-L78】【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L293-L360】
- **Lifecycle statuses** progress from **Lead → Option → Confirmed**, with cancellations tracked explicitly; these values are stored in both `event.status` metadata and the legacy `event_data` mirror.【F:backend/domain/models.py†L24-L60】【F:backend/workflows/io/database.py†L242-L259】【F:backend/workflows/steps/step7_confirmation/trigger/process.py†L260-L318】
- **Context snapshots** are bounded to the current user: the last five history entries plus the newest event, redacted to previews, and hashed via `context_hash` for cache safety.【F:backend/workflows/io/database.py†L190-L206】【F:backend/workflows/common/types.py†L47-L80】

## How control flows (Steps 1–7)
Each step applies an entry guard, deterministic actions, and explicit exits/detours.

### Step 1 — Intake & Data Capture
- **Entry guard:** Incoming mail is classified; anything below 0.85 confidence or non-event intent is routed to manual review with a draft holding response.【F:backend/workflows/steps/step1_intake/trigger/process.py†L33-L100】
- **Primary actions:** Upsert client by email, append history, capture bounded context, create or refresh the event record, merge profile updates, and compute `requirements_hash` for caching.【F:backend/workflows/steps/step1_intake/trigger/process.py†L41-L205】
- **Detours & exits:** Missing or updated dates/requirements trigger `caller_step` bookkeeping and reroute to Step 2 or 3 while logging audit entries.【F:backend/workflows/steps/step1_intake/trigger/process.py†L122-L184】
- **Persistence:** Event metadata stores requirements, hashes, chosen date, and resets room evaluation locks as needed.【F:backend/workflows/steps/step1_intake/trigger/process.py†L111-L168】

### Step 2 — Date Confirmation
- **Entry guard:** Requires an event record; otherwise halts with `date_invalid`. If no confirmed date, proposes deterministic slots via `suggest_dates`.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L21-L90】
- **Actions:** Resolve the confirmed date from user info (ISO or DD.MM.YYYY), tag the source message, update `chosen_date/date_confirmed`, and link the event back to the client profile.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L92-L158】
- **Reminder:** Clients often reply with just a timestamp (e.g. `2027-01-28 18:00–22:00`) when a thread is already escalated. `_message_signals_confirmation` explicitly treats these bare date/time strings as confirmations; keep this heuristic in place whenever adjusting Step 2 detection so we don't re-open manual-review loops for simple confirmations.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L1417-L1449】
- **Guardrail:** `_resolve_confirmation_window` normalizes parsed times, drops invalid `end <= start`, backfills a missing end-time by scanning the message, and now maps relative replies such as "Thursday works", "Friday next week", or "Friday in the first October week" onto the proposed candidate list before validation. Preserve this cleanup so confirmations don't regress into "end time before start time" loops or re-trigger HIL drafts.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L1527-L1676】
- **Parser upgrade:** `parse_first_date` falls back to `resolve_relative_date`, so relative phrasing (next week, next month, ordinal weeks) is converted to ISO dates before downstream checks. Pass `allow_relative=False` only when you deliberately need raw numeric parsing, as `_determine_date` does prior to candidate matching.【F:backend/workflows/common/datetime_parse.py†L102-L143】【F:backend/workflows/common/relative_dates.py†L18-L126】
- **Exits:** Returns to caller if invoked from a detour, otherwise advances to Step 3 with in-progress thread state and an approval-ready confirmation draft.【F:backend/workflows/steps/step2_date_confirmation/trigger/process.py†L125-L159】

#### Regression trap: quoted confirmations triggering General Q&A
- **Root cause:** Email clients quote the entire intake brief beneath short replies such as `2026-11-20 15:00–22:00`. `detect_general_room_query` sees that quoted text, flags `is_general=True`, we dive into `_present_general_room_qna`, emit the "It appears there is no specific information available" fallback, and Step 3 never autoloads even though the client just confirmed the slot.
- **Guardrail:** After parsing `state.user_info`, Step 2 now forces `classification["is_general"] = False` when a valid date/time is extracted. This override ensures the workflow proceeds to Step 3.

---

## Universal Verbalizer: Hard Facts & Unit Verification

**CRITICAL - When adding new product pricing or modifying verbalization:**

The Universal Verbalizer (`backend/ux/universal_verbalizer.py`) enforces that LLM-generated prose preserves all "hard facts" from structured data. Fallbacks occur when verification fails.

### How Hard Facts Work

1. **Extraction**: `_extract_hard_facts()` pulls dates, amounts, room names, products, and **units** from the message context
2. **Verification**: `_verify_facts()` checks that LLM output contains all extracted facts
3. **Patching**: `_patch_facts()` attempts to fix missing facts before falling back to templates
4. **Fallback**: If patching fails, deterministic template is used (logs: `patching failed, using fallback`)

### Common Fallback: Missing Units

**Symptom**: Logs show `patching failed for step=4, topic=offer_intro` with `Missing: ['unit:per event']`

**Root Cause**: The LLM wrote `"CHF 75.00"` but the product data specified `"CHF 75.00 per event"`. The verifier treats missing units as hard fact violations.

**Prevention Checklist**:

| Area | What to Check |
|------|---------------|
| **Prompt facts** | `_format_facts_for_prompt()` must include units in product summaries, e.g., `"Projector (CHF 75.00 per event)"` |
| **HARD RULES** | System prompt must explicitly require units with prices |
| **Unit alternatives** | `_verify_facts()` has `unit_alternatives` dict mapping synonyms (e.g., "per person" ↔ "per guest") |
| **Patching logic** | `_patch_facts()` can append missing units after product prices if single unit type |

### Supported Unit Types

All unit types that may appear in product data:
- `per event` / `per booking` / `flat fee`
- `per person` / `per guest` / `per head`
- `per hour` / `hourly`
- `per day` / `daily`
- `per night` / `nightly`
- `per week` / `weekly`

### Debugging Fallbacks

1. Check logs for `_verify_facts` output: `OK: True/False, Missing: [...], Invented: [...]`
2. If `Missing` contains `unit:*`, the LLM omitted a required unit
3. If `Invented` contains `amount:*`, the LLM hallucinated a price
4. Search for `patching failed` to find fallback occurrences

**Key File**: `backend/ux/universal_verbalizer.py` (lines 170-230 for prompts, 880-950 for verification, 1000-1110 for patching)

---

## Known Bugs & Issues (2026-01-05)

### BUG-001: Post-HIL Step Mismatch
**Status**: Open
**Severity**: Medium
**Symptom**: After HIL approval at Step 5, thread routing thinks it's at Step 2 while event is at Step 5. Next client message gets blocked as "out of context".
**Reproduction**: Complete booking flow → HIL approves offer → client sends follow-up → "Intent 'X' is only valid at steps {4, 5}, but current step is 2"
**Root Cause**: Thread state not synced with event state after HIL task approval.
**Files**: `backend/api/routes/tasks.py`, `backend/workflows/runtime/pre_route.py`

### BUG-002: Q&A Doesn't Answer Room Pricing
**Status**: Open
**Severity**: Low
**Symptom**: "How much does Room A cost?" returns room capacity info but not price.
**Expected**: Should answer with room rental rate (e.g., CHF 500/day).
**Files**: `backend/workflows/common/general_qna.py`, `backend/workflows/qna/router.py`

### BUG-003: Hybrid Messages Ignore Q&A Part
**Status**: Open
**Severity**: Medium
**Symptom**: Message like "Book room for April 5 + do you have parking?" handles booking but drops parking question.
**Expected**: Should answer both booking AND Q&A in same response.
**Files**: `backend/detection/unified.py`, `backend/workflows/steps/step1_intake/trigger/step1_handler.py`
