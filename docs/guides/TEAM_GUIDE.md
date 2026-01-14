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

## HIGH-RISK: Regex-Based Detection Areas (Bug Magnets)

**CRITICAL WARNING:** The following 4 detection areas still use regex/keyword matching instead of LLM semantic understanding. These are the most common source of bugs due to:
- False positives (keywords in wrong context)
- False negatives (paraphrased intent missed)
- Interference with other flows (one detection consuming input meant for another)

| # | Detection Area | Location | Common Issues |
|---|----------------|----------|---------------|
| 1 | **Billing Address Capture** | `step5_handler.py` | Consumes messages meant for date/room changes (BUG-023) |
| 2 | **Site Visit Keywords** | `router.py` | False positives from emails/URLs containing "tour" (BUG-021) |
| 3 | **Date Change Detection** | `change_propagation.py` | Format mismatches causing loops (BUG-020) |
| 4 | **Room Selection Shortcuts** | `step1_handler.py`, `room_detection.py` | Auto-locks room before arrangement requests processed |

**Prevention Pattern:** When adding code in these areas:
1. Always add **early-exit guards** for higher-priority intents (e.g., date change before billing capture)
2. Use **word-boundary regex** (`\btour\b`) not substring matching (`"tour" in text`)
3. **Normalize values** before comparison (ISO dates, lowercase room names)
4. Add **regression tests** for each new pattern

**Long-term:** Migrate these to LLM-based semantic detection when cost/latency allows.

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
**Status**: Fixed (2026-01-13)
**Severity**: Medium (UX clarity)
**Symptom**: When client confirms a room after Step 3 (e.g., "Room A sounds perfect"), the response header still shows "Availability overview" instead of "Offer". The Manager Tasks correctly shows "Step 4" and "offer message".
**Root Cause**: Room confirmation was creating a separate draft message in Step 3 that got superseded by Step 4's offer. The two messages weren't being combined.
**Fix**: Implemented room confirmation prefix mechanism:
1. Step 3 stores `room_confirmation_prefix` ("Great choice! Room X is confirmed...") in event_entry
2. Step 3 returns `halt=False` to continue immediately to Step 4
3. Step 4 pops prefix and prepends it to offer body
Result: One combined message with "Great choice! Room F is confirmed... Here is your offer..."
**Files**: `workflows/steps/step3_room_availability/trigger/step3_handler.py`, `workflows/steps/step4_offer/trigger/step4_handler.py`
**Tests**: `tests/regression/test_room_confirm_offer_combined.py`

### BUG-012: Offer Missing Pricing When Triggered via Room Confirmation
**Status**: Fixed (2026-01-13) - Part of BUG-011 fix
**Severity**: High (missing critical info)
**Symptom**: When offer is triggered via room confirmation shortcut, the draft shows room details (capacity, features) but NO pricing (CHF amount).
**Root Cause**: Room confirmation shortcut was creating a separate Step 3 draft instead of proceeding to Step 4's full offer pipeline.
**Fix**: Same as BUG-011 - Step 3 now returns `halt=False` so Step 4's full offer generation runs, including pricing.
**Files**: Same as BUG-011

### BUG-015: Deposit Payment Does Not Trigger Step 7 (Site Visit / Confirmation)
**Status**: Fixed (2026-01-13)
**Severity**: Critical (Workflow Breaking)
**Symptom**: After clicking "Pay Deposit" button, nothing happens or a generic fallback message appears instead of proper confirmation/site visit message.
**Root Cause**: Four issues found:
1. In `step5_handler.py`, when `gate_status.ready_for_hil` was True, the handler returned `halt=True` instead of `halt=False`
2. In `pre_route.py`, the out-of-context detection was blocking `deposit_just_paid` messages (classified as `confirm_date`)
3. In `step7_handler.py`, the `deposit_just_paid` message flag wasn't checked before classification, causing misclassification to "question" → generic fallback
4. In `page.tsx`, the `confirmation_message` task type wasn't in the `canAction` list, so Step 7 HIL tasks had no Approve button
**Fix**:
1. Changed `halt=True` to `halt=False` in the `ready_for_hil` branch (step5_handler.py)
2. Added bypass for `deposit_just_paid` messages in `check_out_of_context()` (pre_route.py)
3. Added early check for `deposit_just_paid` flag before classification (step7_handler.py)
4. Added `transition_message` and `confirmation_message` to `canAction` list (page.tsx)
**Files**:
- `workflows/steps/step5_negotiation/trigger/step5_handler.py`
- `workflows/runtime/pre_route.py`
- `workflows/steps/step7_confirmation/trigger/step7_handler.py`
- `atelier-ai-frontend/app/page.tsx`
**Tests**: `tests/regression/test_deposit_triggers_step7.py` (6 tests)
**E2E Verified**: Full flow from inquiry → room → offer → accept → billing → deposit → Step 7 HIL → confirmation message in chat.
**Note**: This was a recurring bug with multiple layers. The fix required changes in 4 files across backend and frontend.

### BUG-016: Deposit Info Showing Before Offer Stage (Backend)
**Status**: Fixed (2026-01-13)
**Severity**: Medium (UX confusion)
**Symptom**: Deposit information returned in API response before Step 4, showing stale/premature deposit data.
**Root Cause**: `_build_event_summary()` in `api/routes/tasks.py` always included `deposit_info` regardless of current workflow step.
**Fix**: Added `current_step >= 4` check before including deposit_info in API response.
**Files**: `api/routes/tasks.py`
**Tests**: `tests/regression/test_deposit_step_gating.py` (13 tests)

### BUG-017: OOC Guidance Blocks Offer Confirmation
**Status**: Fixed (2026-01-13)
**Severity**: High (workflow blocked)
**Symptom**: Client replies like "that's fine" after the offer in Step 5 and gets "We're in negotiation..." guidance instead of billing/deposit prompts.
**Root Cause**: `pre_route.check_out_of_context` relied on unified intent labels; simple confirmations were misclassified as `confirm_date`, triggering out-of-context guidance before Step 5.
**Fix**: Treat confirmation/acceptance signals as in-context for Steps 4-5 and gate OOC on intent evidence (date/acceptance/rejection/counter signals + billing detection).
**Files**: `workflows/runtime/pre_route.py`
**Tests**: `tests/specs/prelaunch/test_prelaunch_regressions.py` (OOC confirmation bypass)

### BUG-014: Deposit UI Showing Before Offer Stage
**Status**: Fixed (2026-01-13)
**Severity**: Medium (UX confusion)
**Symptom**: Dynamic deposit UI ("💰 Deposit Required: CHF X") showing before client even started a conversation, displaying stale deposits from previous sessions.
**Root Cause**: Frontend `unpaidDepositInfo` computed value used all tasks without filtering by current session's `thread_id`.
**Fix**:
1. Added early return if `sessionId` is null (no session = no deposit)
2. Filter tasks by `thread_id === sessionId` to only show deposits for current conversation
**Files**: `atelier-ai-frontend/app/page.tsx`
**Note**: This fix only applies to development-branch (frontend). Main branch is backend-only.

### BUG-018: Detection Interference - Regex Overriding LLM Signals
**Status**: Fixed (2026-01-13)
**Severity**: High (incorrect routing)
**Symptom**: Multiple detection issues where regex/keyword patterns override correct LLM semantic intent:
1. Step5 acceptance regex too permissive ("good" alone triggers acceptance)
2. Step7 "Yes, can we visit next week?" returns confirm instead of site_visit
3. Room detection "Is Room A available?" incorrectly locks Room A
4. Q&A borderline heuristics ("need room") can't be vetoed by LLM
**Root Cause**: Detection code was checking regex/keywords before consulting unified LLM detection signals, and in some cases ignoring the signals entirely.
**Fix**: Implemented unified detection consumption across 4 areas:
1. Step5: Use `unified_detection.is_acceptance/is_rejection` before regex fallback
2. Step7: Check `qna_types` for `site_visit_request` before CONFIRM_KEYWORDS
3. Room detection: Add question guard (? in text OR `is_question=True`)
4. Q&A: Require LLM agreement for borderline heuristic matches
**Files**:
- `workflows/steps/step5_negotiation/trigger/classification.py` - unified acceptance/rejection
- `workflows/steps/step7_confirmation/trigger/classification.py` - site visit precedence
- `workflows/steps/step1_intake/trigger/room_detection.py` - question guard
- `detection/qna/general_qna.py` - LLM veto logic for borderline
**Tests**: `tests/detection/test_detection_interference.py` (13 tests: DET_INT_001 through DET_INT_010 + variants)
**Zero Cost**: All fixes reuse unified detection already computed during pre-routing ($0 extra LLM calls)

### BUG-019: Global Deposit Config Not Applied to New Events
**Status**: Open (2026-01-13)
**Severity**: High (missing deposit)
**Symptom**: Despite configuring global deposit in UI (30%, 10 days), new events don't have `deposit_info` populated, and no deposit button appears after offer acceptance.
**Root Cause**: Timing issue - the global deposit config must be saved to database BEFORE starting a new conversation. If events are created before the config is persisted, they won't pick up the deposit settings.
**Workaround**: Ensure "Reset Client" and new conversation happens AFTER global deposit is configured and saved.
**Investigation Needed**:
1. The `state.db` snapshot might be stale when Step 4 calls `build_deposit_info()`
2. Consider reloading config from database at offer generation time
3. Check if `load_db()` in workflow_email.py needs refresh after config updates
4. Verify `build_deposit_info()` is reading from persisted config, not in-memory snapshot
**Reproduction**:
1. Start new conversation (event created)
2. In another tab, configure global deposit (30%, 10 days)
3. Continue conversation to offer acceptance
4. Result: No deposit button appears
**Files**:
- `workflows/steps/step4_offer/trigger/step4_handler.py:615-618` - build_deposit_info call
- `backend/workflow_email.py` - state.db initialization
- `backend/workflows/io/database.py` - config persistence

### BUG-020: Date Change Detour Loop (Step2 ↔ Step4 Endless Loop)
**Status**: Fixed (2026-01-13)
**Severity**: Critical (workflow stuck)
**Symptom**: When regenerating an offer after a detour (e.g., returning from Step 2 date confirmation), the workflow would endlessly loop between Step 2 and Step 4. The message containing the date was re-detected as a date change, triggering another detour.
**Root Cause**: `detect_change_type_enhanced()` in `change_propagation.py` compared old and new date values as raw strings without normalizing formats. Dates like "05.03.2026" vs "2026-03-05" were treated as different, triggering spurious detours.
**Fix**: Added `_normalize_date_value()` helper that converts any date format to ISO YYYY-MM-DD before comparison. If normalized old and new dates match, returns `is_change=False` instead of triggering a detour.
**Files**: `workflows/change_propagation.py` (lines 849-866, 1055-1070)

### BUG-021: Site Visit Keyword False Positives from Email Addresses
**Status**: Fixed (2026-01-13)
**Severity**: Medium
**Symptom**: Site visit intercept triggered incorrectly when email addresses or URLs contained substrings matching site visit keywords (e.g., "detour" in email addresses, "tour" inside URLs).
**Root Cause**: `_check_site_visit_intercept()` in `router.py` used simple substring matching (`kw in message_lower`) which matched keywords embedded within email addresses and URLs.
**Fix**:
1. Strip email addresses and URLs from message text before keyword matching
2. Changed from substring matching to regex word-boundary patterns (`\bsite\s+visit\b`, `\btour\b`, etc.)
**Files**: `workflows/runtime/router.py` (lines 190-210)
**Prevention**: Always use word-boundary regex for keyword detection to avoid false positives from structured text.

### BUG-022: Deposit UI Showing Before Offer Acceptance
**Status**: Fixed (2026-01-13)
**Severity**: High (UX confusing)
**Symptom**: Deposit card and "Pay Deposit" button appeared in the frontend as soon as an offer was drafted (Step 4), before the client actually accepted the offer.
**Root Cause**:
1. Backend sets `current_step=5` immediately after drafting the offer (pre-acceptance)
2. Frontend showed deposit button whenever `deposit_info` existed and `current_step >= 4`
**Fix**:
1. Added `offer_accepted` field to `deposit_info` in API responses
2. Gated frontend deposit UI and "Mark Deposit Paid" button on `offer_accepted === true`
**Files**:
- `api/routes/messages.py` - add `offer_accepted` to deposit_info
- `api/routes/tasks.py` - add `offer_accepted` to event_summary.deposit_info
- `atelier-ai-frontend/app/page.tsx` - gate deposit UI on `offer_accepted`
**Tests**: `tests_root/specs/gatekeeping/test_hil_gates.py`

### BUG-023: Billing Capture Mode Interferes with Date Change Detection
**Status**: Fixed (2026-01-13)
**Severity**: Medium
**Symptom**: When in billing capture mode (awaiting billing address after offer acceptance), a date change request like "Actually, I need to change the date to March 20, 2026" gets captured as billing address instead of triggering date change detection.
**Root Cause**: Billing capture mode blindly captured any message as billing address without checking for higher-priority intents like date changes.
**Fix**: Added `_looks_like_date_change()` guard in `step5_handler.py` that checks for date change intent (change verbs + date keywords/patterns) BEFORE billing capture. If detected, skips billing capture and lets change detection handle the message.
**Files**: `workflows/steps/step5_negotiation/trigger/step5_handler.py` (lines 85-110, 196-201)
**E2E Reference**: `backend/e2e-scenarios/2026-01-13_date-change-detour-after-offer.md`

### BUG-024: Date Change During Billing Capture Not Acknowledged in Response
**Status**: Fixed (2026-01-14)
**Severity**: Medium (UX Issue)
**Symptom**: When client requests a date change while in billing capture mode (after accepting offer, before providing billing address), the date IS changed in the database but the response only prompts for billing without acknowledging the date change.
**Root Cause**: Two issues:
1. `step1_handler.py` detected the date change and logged it, but didn't actually update `event_entry.chosen_date` or set an acknowledgment flag
2. `step5_handler.py` used wrong key (`body`) instead of `body_markdown` when prepending acknowledgment to billing prompt
**Fix**:
1. In `step1_handler.py` (lines 1532-1542): Added `update_event_metadata()` call and `_pending_date_change_ack` flag setting when date change detected during billing flow
2. In `step5_handler.py` (line 307): Changed `next_prompt["body"]` to `next_prompt["body_markdown"]` to match the actual key from `get_next_prompt()`
**Files**:
- `workflows/steps/step1_intake/trigger/step1_handler.py` (lines 1532-1542)
- `workflows/steps/step5_negotiation/trigger/step5_handler.py` (line 307)
**Tests**: E2E verified - date change to 20.06.2026 acknowledged in response: "I've updated your event to **20.06.2026**. Thanks for confirming..."

### BUG-025: Date Change Detour Not Triggering During Billing Flow
**Status**: Fixed (2026-01-14)
**Severity**: High (Workflow Breaking)
**Symptom**: When client requests a date change while in billing flow (after accepting offer), the system kept asking for billing address instead of triggering the detour to Step 2 → Step 3 → Step 4 with a new offer.
**Root Cause**: The `correct_billing_flow_step()` function in `pre_route.py` was forcing `current_step=5` whenever `in_billing_flow` was true. This ran AFTER step1_handler detected the date change and set the step to 2, overwriting the detour routing.
**Fix**: In `step1_handler.py`, when a date change is detected during billing flow, clear the billing flow state (`awaiting_billing_for_accept=False`, `offer_accepted=False`) BEFORE the step change. This ensures `correct_billing_flow_step()` sees `in_billing_flow=False` and doesn't override the detour.
**Files**:
- `workflows/steps/step1_intake/trigger/step1_handler.py` (lines 1258-1268)
**E2E Reference**: `backend/e2e-scenarios/2026-01-14_date-change-during-billing-flow.md`
**Related Bugs**: Builds on BUG-023 (billing capture interference) and BUG-024 (date change acknowledgment)

### BUG-026: HIL Approval Shows body_markdown Instead of body
**Status**: Fixed (2026-01-14)
**Severity**: High (UX Breaking)
**Symptom**: After manager clicks "Approve & Send" on a Step 7 HIL task, the chat displayed the offer summary (`body_markdown`) instead of the site visit prompt (`body`).
**Root Cause**: The `add_draft_message()` function in `workflows/common/types.py` was always overwriting `body` with content derived from `body_markdown` at lines 234-235, even when both were explicitly provided and different.
**Design Principle**:
- `body` = client-facing message (e.g., site visit prompt)
- `body_markdown` = manager-only display in HIL panel (e.g., offer summary for review)
- When they differ, client ALWAYS receives `body`
**Fix**:
1. Modified `add_draft_message()` to preserve original `body` when both fields are explicitly provided and different
2. Added defensive code and logging in `hil_tasks.py` when body differs from body_markdown
**Files**:
- `workflows/common/types.py` - Preserve body when body_markdown differs
- `workflows/runtime/hil_tasks.py` - Defensive code + warning log
- `main.py` - Added `logging.basicConfig()` for logger visibility
**Tests**: `tests/regression/test_hil_body_vs_markdown.py` (3 tests)
**E2E Verified**: `.playwright-mcp/.playwright-mcp/e2e-hil-body-fix-verified.png`
**Related Bugs**: Opposite of BUG-013 (which had site visit text replacing offer draft)

### BUG-027: Site Visit Auto-Selecting Dates and "14:00" Parsing as Date
**Status**: Fixed (2026-01-14)
**Severity**: Medium (UX/Flow Issue)
**Symptom**:
1. When room conflicts occurred during site visit scheduling, the system auto-selected an alternative date instead of offering options to the client
2. Time pattern "14:00" was being incorrectly parsed as a date, causing flow errors
**Root Cause**: Site visit flow combined date and time selection in a single step, leading to premature decisions and parsing ambiguities.
**Fix**: Implemented 2-step site visit flow:
1. **Step 1 - Date Selection**: Agent offers 3-5 available dates → client selects one
2. **Step 2 - Time Selection**: Agent offers time slots (10:00, 14:00, 16:00) for selected date → client selects one
3. Added `time_pending` status to track "date selected, waiting for time" state
4. Added `proposed_dates` and `selected_date` fields to SiteVisitState
5. Separated handler functions: `_handle_date_selection()` and `_handle_time_selection()`
6. Fixed `_date_conflict_response()` to offer alternatives instead of auto-selecting
**Files**:
- `workflows/common/site_visit_state.py` - State model updates
- `workflows/common/site_visit_handler.py` - 2-step flow implementation
**Tests**: All 28 site visit tests pass
**E2E Verified**: Playwright test confirms separate date/time selection prompts work correctly
**Design Principle**: Client must explicitly select BOTH date and time - no auto-selection or fallback logic

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
