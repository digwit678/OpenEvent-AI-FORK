# New Features & Ideas

Ideas collected during development sessions for future implementation.

---

## ✅ IMPLEMENTED: Event-Relative Deposit Due Date (Jan 14, 2026)

**Status:** Implemented on 2026-01-14. See DEV_CHANGELOG.md for details.

**Implementation:** Modified `calculate_deposit_due_date()` in `workflows/common/pricing.py`:
- Added `event_date` parameter (optional)
- Added `min_days_before_event` config option (default 14 days)
- Due date = `min(today + deadline_days, event_date - min_days_before_event)`
- Ensures due date is at least 1 day from today

**Files modified:**
- `workflows/common/pricing.py` - Updated `calculate_deposit_due_date()` and `build_deposit_info()`
- `workflows/steps/step4_offer/trigger/step4_handler.py` - Pass event date to deposit calculation

---

## Detection Interference Hardening (Jan 13, 2026)

**Context:** OOC guidance bug triage surfaced multiple detection conflicts (acceptance vs room/date, shortcuts, Q&A heuristics).

**Proposed Solution:** Gate high-impact routing with existing unified detection outputs, and strip quoted history before regex-driven routing.

**Details:** See `docs/reports/DETECTION_INTERFERENCE_IDEAS.md` (cost notes + full list).

**Files to modify:** `workflows/runtime/pre_route.py`, `workflows/steps/step1_intake/trigger/*`, `workflows/planner/*`, `detection/qna/general_qna.py`.

**Priority:** Medium (robustness).

## LLM-Based Site Visit Detection (Jan 13, 2026)

**Context:** Current site visit detection in `workflows/runtime/router.py` relies on regex and keyword matching. While improved with email/URL stripping, it still risks false positives or missing nuanced requests.

**Proposed Solution:** Move site visit detection into the unified LLM-based intent classification. Use the LLM to distinguish between "I want to visit" and "How do I visit?" or "I visited before".

**Files to modify:** `workflows/runtime/router.py`, `backend/llm/intent_classifier.py`, `detection/site_visit/`.

**Priority:** Medium.

---

## On-Demand Site Visit Scheduling (Any Step + Confirm Gate) (Mar 2026)

**Context:** Site visits are currently default after offer steps and can auto-confirm when a date is proposed. Clients want to book at any step, and scheduling should never auto-confirm without explicit client confirmation.

**Proposed Solution:** Reuse unified detection output (no extra LLM cost) to trigger site visit requests at any step, add a confirm_pending state so booking only happens after explicit confirmation, and default suggestions to event_date - 7 days (or today + 7 if no event date). See `docs/plans/active/site_visit_on_demand_plan.md`.

**Files to modify:** `detection/unified.py`, `workflows/runtime/router.py`, `workflows/common/site_visit_handler.py`, `workflows/common/site_visit_state.py`, `workflows/common/room_rules.py`, `tests/*`.

**Priority:** High.

---

## Mandatory Time Slot Booking (Event + Site Visit) (Mar 2026)

**Context:** Date confirmations currently default to a single slot label and do not enforce time selection. Site visits use hour-based slots and can confirm without a time range. We need manager-defined time ranges and mandatory slot selection for every booked date.

**Proposed Solution:** Introduce manager-configured time ranges for event and site visit bookings, enforce time-slot selection unless the client explicitly requests full-day or multi-day bookings, and route time-slot prompts/suggestions through the verbalizer. Group dates under shared time ranges to avoid repeating the same slots. See `docs/plans/active/time_slot_booking_plan.md` and `docs/plans/active/time_slot_booking_implementation_plan.md`.

**Files to modify:** `workflows/io/config_store.py`, `workflows/steps/step2_date_confirmation/trigger/step2_handler.py`, `workflows/common/site_visit_handler.py`, `ux/universal_verbalizer.py`, `api/routes/config.py`, `tests/*`.

**Priority:** High.

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
