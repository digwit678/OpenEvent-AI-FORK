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

**Must-set env vars for production:**
- `AUTH_ENABLED=1` - Otherwise all endpoints are public
- `ENV=prod` - Hides debug routes, reduces health endpoint info exposure

**Optional hardening env vars:**
- `REQUEST_SIZE_LIMIT_KB=1024` - Max request body size (default 1MB)
- `LLM_CACHE_MAX_SIZE=500` - Max LLM analysis cache entries (default 500)

**Remaining risks:**
- LLM input sanitization is not wired into unified detection/Q&A/verbalizer entrypoints yet.
- Mock deposit payment endpoint should be gated or disabled in production.
- Snapshot storage uses local JSON (not suitable for multi-worker deployments).

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
**Status**: Fixed (2026-01-05)
**Severity**: Medium
**Symptom**: After HIL approval at Step 5, thread routing thinks it's at Step 2 while event is at Step 5. Next client message gets blocked as "out of context".
**Root Cause**: `_ensure_event_record` was treating `site_visit_state.status == "proposed"` as a terminal state and creating a new event, when it's actually a mid-flow state.
**Fix**: Changed site visit status check to only treat "completed", "declined", "no_show" as terminal states.
**Files**: `backend/workflows/steps/step1_intake/trigger/step1_handler.py:1166-1175`

### BUG-002: Q&A Doesn't Answer Room Pricing
**Status**: Fixed (2026-01-05)
**Severity**: Low
**Symptom**: "How much does Room A cost?" returns room capacity info but not price.
**Root Cause**: `load_room_static` and `RoomSummary` didn't include room pricing data.
**Fix**: Added `daily_rate` and `daily_rate_formatted` fields to room data structures and Q&A fallback formatter.
**Files**: `backend/services/qna_readonly.py`, `backend/workflows/qna/engine.py`, `backend/workflows/qna/verbalizer.py`

### BUG-003: Hybrid Messages Ignore Q&A Part
**Status**: Fixed (2026-01-12)
**Severity**: Medium
**Symptom**: Message like "Room B looks great + which rooms in February?" handles room confirmation but drops Q&A question.
**Root Cause**:
1. Step 1 intake processed booking intent but didn't check for `qna_types` in unified detection
2. **Timing issue**: `unified_detection` is populated AFTER `intake.process(state)` runs, so room shortcut couldn't access `qna_types`
3. Month-constrained availability patterns ("available in February") weren't detected
4. "Next year" relative date wasn't handled
**Fix**:
1. Added `generate_hybrid_qna_response()` function and hook in step 1
2. Added fallback to `_general_qna_classification.secondary` when `unified_detection` not available
3. Store `hybrid_qna_response` on `state.extras` so it survives across steps
4. Added month-constrained patterns to `_QNA_REGEX_PATTERNS["free_dates"]`
5. Added `force_next_year` detection to `_extract_anchor()` and `_resolve_anchor_date()`
6. Added German month names support
**Files**: `workflows/qna/router.py`, `workflows/steps/step1_intake/trigger/step1_handler.py`, `workflow_email.py`, `detection/intent/classifier.py`, `workflows/common/catalog.py`
**Tests**: `tests/detection/test_hybrid_qna.py` (18 tests)

**Hybrid Detection Requirements (for testing):**
1. Message recognized as hybrid (confirmation + Q&A)
2. Q&A part extracted correctly and NOT confused with main workflow part
3. Response includes 2 sections: (a) workflow response, (b) Q&A answer
4. Must work from every step: hybrid confirmation + Q&A, hybrid detours + Q&A, hybrid shortcuts + Q&A
5. Month-constrained queries detect `free_dates` type (e.g., "available in February")
6. "Next year" detection works (EN + DE)

### BUG-004: Product Arrangement Request Bypassed by Step 1 Auto-Lock
**Status**: Fixed (2026-01-07)
**Severity**: High
**Symptom**: When client says "Room A sounds good, please arrange the flipchart", the system shows catering fallback ("Before I prepare your tailored proposal...") instead of acknowledging the arrangement request.
**Root Cause**: Step 1's `room_choice_captured` logic auto-locked the room AND set `current_step=4` when detecting room selection phrases, completely bypassing Step 3's arrangement detection.
**Investigation Path**:
1. Added `[ROUTER]` debug logging in `router.py` to trace `current_step` values
2. Discovered second message had `current_step=4, locked_room=Room A` BEFORE routing loop ran
3. Traced to `step1_handler.py:837-873` where room choice detection locks and advances step
**Fix**: Added bypass check in step1_handler: if `room_pending_decision` has `missing_products`, don't auto-lock or advance to step 4. Let step 3 handle the arrangement request detection.
**Files**: `workflows/steps/step1_intake/trigger/step1_handler.py:837-873`
**Learning**: When implementing "fast path" shortcuts, always check for blocking conditions from related flows. Room selection shortcut must respect pending arrangement requests.

### BUG-005: Arrangement Detection After Change Detection (Order Bug)
**Status**: Fixed (2026-01-07)
**Severity**: High
**Symptom**: Even after fixing BUG-004, arrangement requests still got catering fallback.
**Root Cause**: In step3_handler, the ARRANGEMENT CHECK code was placed AFTER the CHANGE_DETECTION section. When client said "arrange the flipchart", it was detected as `ChangeType.REQUIREMENTS` and routed to a detour BEFORE the arrangement check could run.
**Fix**: Moved arrangement detection to run BEFORE change detection (added "EARLY ARRANGEMENT CHECK" section at line 248-279 in step3_handler.py).
**Files**: `workflows/steps/step3_room_availability/trigger/step3_handler.py:248-279`
**Learning**: Detection priority matters! Specific intent detection (like arrangement requests) must run before generic change detection to avoid misclassification.

### BUG-006: Smart Shortcuts Gate Missing Product Check
**Status**: Fixed (2026-01-07)
**Severity**: Medium
**Symptom**: Smart shortcuts were intercepting room selection messages even when there were missing products to arrange.
**Root Cause**: `shortcuts_gate.py` didn't check for `missing_products` in `room_pending_decision` before allowing shortcuts to run.
**Fix**: Added bypass in `shortcuts_allowed()` - return False if `room_pending` exists, room isn't locked, and there are missing products.
**Files**: `workflows/planner/shortcuts_gate.py:39-52`

### BUG-007: Products Prompt Still Appearing After Room Selection
**Status**: Fixed (2026-01-12) - MVP Decision
**Severity**: High (UX Critical)
**Symptom**: After selecting a room, Step 4 showed "Before I prepare your tailored proposal, could you share which catering or add-ons you'd like to include?" instead of going directly to the offer.
**Root Cause**: `products_ready()` gate in Step 4 was checking various conditions to determine if products were "ready", creating unnecessary blocking prompts.
**MVP Decision**: Catering/products awareness belongs IN THE OFFER ITSELF, not as a separate blocking prompt. If client hasn't mentioned products, the offer should include suggestions but NOT block the flow.
**Fix**: Made `products_ready()` always return True. Catering options are now displayed in the offer's "Menu options you can add" section.
**Files**: `workflows/steps/step4_offer/trigger/product_ops.py`
**E2E Verified**: Full flow from inquiry → room → offer → billing → HIL → site visit works without products prompt.

### BUG-008: Hybrid Messages (Room + Catering Q&A) Ignore Q&A Part
**Status**: Fixed (2026-01-12)
**Severity**: High
**Symptom**: Messages like "Room C sounds great! Also, could you share more about your catering options?" were confirming the room but ignoring the catering question portion.
**Root Cause**: Sequential workflow detection patterns were too restrictive and didn't match indirect catering question phrases like "share more about", "about your catering".
**Fix**:
1. Added flexible regex patterns in `sequential_workflow.py` for room selection ("sounds great/good/perfect", "please proceed") and catering questions ("share more about", "about your catering")
2. Added `sequential_catering_lookahead` handling in `step3_handler.py` to ensure catering info is appended to room confirmation
**Files**: `detection/qna/sequential_workflow.py`, `workflows/steps/step3_room_availability/trigger/step3_handler.py`

### BUG-009: Q&A Date Constraints Bleeding Into Main Workflow
**Status**: Fixed (2026-01-12)
**Severity**: High
**Symptom**: Hybrid message "Room B looks great, let's proceed with that. By the way, which rooms would be available for a larger event in February next year?" would reset the confirmed date and go back to Step 2 instead of proceeding with room selection.
**Root Cause**: Two issues:
1. LLM extracts `vague_month='february'` from the Q&A question
2. This triggers `needs_vague_date_confirmation` in Step 1
3. Step 1 resets `date_confirmed=False` and routes to Step 2
4. Additionally, Step 1's room shortcut was bypassing Q&A handling entirely
**Fix**:
1. Added Q&A date guard in Step 1 (lines 924-949): Don't reset date when `general_qna_detected` AND `date_confirmed` are both True
2. Added Q&A bypass in Step 1 room shortcut (lines 841-856): When Q&A is detected, don't use shortcut - let Step 3 handle hybrid via `deferred_general_qna`
**Files**: `workflows/steps/step1_intake/trigger/step1_handler.py`
**Key Learning**: Q&A should be isolated from main workflow state. Q&A constraints (like `vague_month` from a question) should only affect Q&A response generation, never modify workflow variables like `date_confirmed`.

### BUG-010: Q&A Response Formatting - Bullets Instead of Inline Features
**Status**: Fixed (2026-01-12)
**Severity**: Low (UX)
**Symptom**: Q&A responses were using bullet points for features which wasted vertical space. User requested features be listed inline with commas (e.g., "rooms a-c, feat 2, ...") and the last call-to-action sentence on a new line without bullet.
**Root Cause**: The `generate_hybrid_qna_response()` function in `router.py` was adding bullet points to all items after the intro line.
**Fix**: Simplified formatting in `router.py` lines 1003-1008: removed bullet logic entirely, using double newlines to separate lines while keeping feature lists inline as they're already joined in source functions (e.g., `list_room_features` joins with commas).
**Files**: `workflows/qna/router.py`

### BUG-011: Room Confirmation Shows "Availability overview" Instead of "Offer"
**Status**: Open (regression found 2026-01-12)
**Severity**: Medium (UX clarity)
**Symptom**: When client confirms a room after Step 3 (e.g., "Room A sounds perfect"), the response header still shows "Availability overview" instead of "Offer". The Manager Tasks correctly shows "Step 4" and "offer message".
**Root Cause**: The `room_choice_captured` shortcut in Step 1 sets `current_step=4` but the draft header is not being set correctly. The offer draft shows room features but wrong header.
**Technical Detail**: `detect_room_choice()` in `room_detection.py` only activates when `current_step >= 3`. Follow-up room confirmations go through Step 1 → shortcut → Step 4. The "Room Confirmed" draft added was superseded or the verbalizer is overwriting the header.
**Reproduction**:
1. Send initial message with date + participants (no room)
2. System shows "Availability overview" with room options
3. Reply "Room A sounds perfect!"
4. Response shows "Availability overview" header instead of "Offer"
**Files**: `workflows/steps/step1_intake/trigger/step1_handler.py`, `ux/universal_verbalizer.py`
**Key Learning**: Draft headers can be overwritten by verbalizer. Need to trace full flow to find where header is set.

### BUG-012: Offer Missing Pricing When Triggered via Room Confirmation
**Status**: Open (2026-01-12)
**Severity**: High (missing critical info)
**Symptom**: When offer is triggered via room confirmation shortcut, the draft shows room details (capacity, features) but NO pricing (CHF amount).
**Comparison**: Smart shortcut (initial message with room+date+participants) correctly shows "Room B · CHF 750.00" and pricing.
**Root Cause**: The room confirmation shortcut path doesn't call the offer pricing generation. The smart shortcut goes through Step 4's full offer pipeline which includes pricing.
**Reproduction**:
1. Send initial message with date + participants (no room)
2. Confirm a room ("Room A sounds perfect!")
3. Response shows room features but no CHF pricing
**Files**: `workflows/steps/step1_intake/trigger/step1_handler.py`, `workflows/steps/step4_offer/`

### BUG-013: HIL Approval Sends Site Visit Text Instead of Workflow Draft
**Status**: Fixed (2026-01-12)
**Severity**: Critical (UX Breaking)
**Symptom**: After manager HIL approval for Step 4/5, the response was always "Let's continue with site visit bookings..." instead of the actual offer confirmation message.
**Root Cause**: In `workflows/runtime/hil_tasks.py`:
1. `_compose_hil_decision_reply()` hardcoded site visit text for all Step 5 approvals
2. Lines 347-353 and 381-388 forced `site_visit_state = "proposed"` prematurely during HIL approval
**Fix**:
1. Removed hardcoded site visit text replacement - now uses actual draft from workflow
2. Removed forced `site_visit_state` setting - let Step 7 handle naturally
**Files**: `workflows/runtime/hil_tasks.py`
**E2E Verified**: Full flow including date change detour - both initial offer confirmation and post-detour offer show correct messages, not site visit text.

---

## Q&A Rules During Detours

### Rule: Q&A Should Use Detoured Date/Room Context

When a detour is triggered (date change, room change, requirements change) AND a Q&A question is asked in the same message:

1. **Date Detour + Catering Q&A**: Use the NEW detoured date as default for catering availability
2. **Room Detour + Catering Q&A**: Show catering options for ALL rooms available on the date (since room is being re-evaluated)
3. **Date + Room Detour**: Show all catering options available on the new date across all rooms

**Implementation**: Q&A handlers should check for detour context in `event_entry` and use the updated values, not cached/stale values.

**Files to update**: `workflows/qna/router.py`, `workflows/qna/general_qna.py`
