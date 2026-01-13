# New Features & Ideas

Ideas collected during development sessions for future implementation.

---

## Detection Interference Hardening (Jan 13, 2026)

**Context:** OOC guidance bug triage surfaced multiple detection conflicts (acceptance vs room/date, shortcuts, Q&A heuristics).

**Proposed Solution:** Gate high-impact routing with existing unified detection outputs, and strip quoted history before regex-driven routing.

**Details:** See `docs/reports/DETECTION_INTERFERENCE_IDEAS.md` (cost notes + full list).

**Files to modify:** `workflows/runtime/pre_route.py`, `workflows/steps/step1_intake/trigger/*`, `workflows/planner/*`, `detection/qna/general_qna.py`.

**Priority:** Medium (robustness).

---

## Capacity Limit Handling (Dec 25, 2025)

**Context:** During capacity change testing, discovered system doesn't handle "capacity exceeds all rooms" case.

**Current Behavior:**
- System shows all rooms even when none fit the requested capacity
- Verbalizer produces contradictory messages ("great fit for 150 guests... capacity of 60")
- No routing to Step 2 for alternative dates

**Proposed Solution:**
1. **Room Filtering:** Add option to `ranking.py` to filter out rooms with `capacity_fit=0`
2. **Step 3 Unavailable Handler:** When no room fits capacity:
   - Display clear message: "Our largest room accommodates 120 guests. For 150 guests, consider..."
   - Suggest alternatives: split into two sessions, external venue partnership, reduce capacity
   - Route to Step 2 if date change might help (e.g., multi-room options on specific dates)
3. **Per Workflow V4 Spec:** "S3_Unavailable: [LLM-Verb] unavailability + propose date/capacity change → [HIL]"

**Files to modify:**
- `backend/rooms/ranking.py` - Add `filter_by_capacity=True` option
- `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py` - Handle "no room fits" branch
- Verbalizer prompts for capacity limit messaging

**Priority:** Medium - edge case but poor UX when it happens

---

## Billing Address Extraction at Every Step (Dec 27, 2025)

**Context:** During E2E testing, noticed billing is only captured after offer confirmation (Step 5).

**Current Behavior:**
- Billing address extraction only triggers in Step 5 when `awaiting_billing_for_accept=True`
- If client proactively provides billing earlier (Step 1-4), it's ignored
- Client may need to repeat billing info after accepting offer

**Proposed Solution:**
1. **Early Billing Detection:** Add billing address regex/NLU to entity extraction in Step 1
2. **Opportunistic Capture:** If billing detected in any step, store to `billing_details` immediately
3. **Skip Prompt:** When reaching Step 5 billing gate, check if `billing_details` already complete
4. **UX Improvement:** Acknowledge early billing: "Thanks for the billing info, I'll use it when we finalize"

**Files to modify:**
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py` - Add billing detection
- `backend/workflows/common/billing.py` - Add `try_capture_billing(message_text, event_entry)`
- `backend/workflows/steps/step5_negotiation/trigger/step5_handler.py` - Check pre-captured billing

**Priority:** Low - nice-to-have UX improvement

---

## ✅ IMPLEMENTED: Smart Shortcut - Initial Message Direct-to-Offer (Jan 12, 2026)

**Status:** Implemented on 2026-01-12. See DEV_CHANGELOG.md for details.

**Implementation:** Added inline availability verification in Step 1 (`step1_handler.py` lines 803-897):
- Detects room + date + participants in initial message
- Calls `evaluate_rooms()` inline to check availability
- If room is available: sets `date_confirmed`, `locked_room_id`, `room_eval_hash`, `current_step=4`
- Returns `action="smart_shortcut_to_offer"` to bypass Steps 2-3

**Tested:** Playwright E2E verified - "I'd like to book Room B for Feb 15, 2026 with 20 participants" → immediate "Offer" header

---

## ✅ IMPLEMENTED: Q&A Detour Context Awareness (Jan 12, 2026)

**Status:** Implemented on 2026-01-12. See DEV_CHANGELOG.md for details.

**Implementation:** Updated `_catering_response()` in `router.py` with priority-based context:
1. Room confirmed → Show catering for that room on that date
2. Date confirmed but room re-evaluating → Show ALL catering from all rooms
3. Neither confirmed (detour) → Show monthly availability (current + next if past 20th)

**Key changes:**
- Comprehensive rule documentation in function docstring
- Context-aware preface messages
- Fixed `_event_date_iso()` to handle multiple date formats

---
