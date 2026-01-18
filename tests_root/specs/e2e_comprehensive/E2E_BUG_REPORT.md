# E2E Bug Report - Detours, Q&A, and Hybrid Messages

This report tracks bugs discovered through TRUE E2E tests.

## Bug #1: Date Change From Step 4 Ends at Step 5 Instead of Step 4

**Status:** ✅ FIXED

**Test:** `test_date_change_full_e2e[4]`

**Root Cause:**
In `workflows/steps/step4_offer/trigger/step4_handler.py`:
1. Lines 617-620 cleared `caller_step=None` early in the handler, BEFORE the offer generation code could check it
2. Lines 727-736 unconditionally advanced to step 5 after generating an offer

**Fix Applied:**
1. Removed early `caller_step=None` clearing at lines 617-620
2. Added logic at lines 729-735 to check `caller_step` and stay at step 4 for detour flows:
```python
if caller is not None:
    # Detour flow: client must respond to regenerated offer, stay at step 4
    next_step = 4
else:
    # Normal flow: advance to step 5
    next_step = 5
```

---

## Bug #2: Steps 6/7 Creating New Events When offer_accepted=True

**Status:** ✅ FIXED

**Test:** `test_room_change_full_e2e[6]`, `test_room_change_full_e2e[7]`

**Root Cause:**
In `workflows/steps/step1_intake/trigger/step1_handler.py` lines 1678-1717:
When `offer_accepted=True`, intake checks if the message is a billing/deposit follow-up. Messages like "Can we switch to Room B?" were incorrectly triggering `should_create_new=True` because they don't look like billing info.

**Fix Applied:**
Added `is_revision_message = has_revision_signal(message_text)` check at line 1704.
Revision messages (containing "change", "switch", "instead", etc.) now continue with the existing event instead of creating a new one.

---

## Bug #3: Step 4 Skipping Offer Generation When offer_accepted=True During Detour

**Status:** ✅ FIXED

**Test:** `test_date_change_full_e2e[6]`, `test_date_change_full_e2e[7]`

**Root Cause:**
In `workflows/steps/step4_offer/trigger/step4_handler.py` lines 178-222:
When `offer_accepted=True`, step 4 goes into a "confirmation gate" path that handles already-accepted offers, instead of regenerating the offer.

**Fix Applied:**
Added check at lines 179-187 to clear `offer_accepted` when `caller_step` is set (detour in progress):
```python
caller_step = event_entry.get("caller_step")
if caller_step is not None and event_entry.get("offer_accepted"):
    event_entry["offer_accepted"] = False
```

---

## Bug #4: Product Add Messages Incorrectly Detected as DATE Change

**Status:** ✅ FIXED

**Test:** `test_product_add_full_e2e[4-7]`

**Root Cause:**
Two issues:
1. In `detection/keywords/buckets.py`, the DATE patterns included `the\s+booking` which incorrectly matched "add a projector to the booking"
2. In `step1_handler.py`, the intake step was rebuilding requirements from user_info, and the LLM extracted product names into `special_requirements`, changing the requirements hash and causing P2 to fail

**Fix Applied:**
1. Removed `the\s+booking` from date patterns in `buckets.py` (too generic)
2. Added products-only detection in `step1_handler.py` that preserves existing requirements when the message only contains product changes

---

## Bug #5: Billing Capture Messages Causing Step Transitions

**Status:** ✅ FIXED

**Test:** `test_billing_capture_full_e2e[4-7]`

**Root Cause:**
Test fixtures didn't set `offer_status` string. Guards in `workflow/guards.py` check `offer_status not in {"sent", "accepted", "accepted_final"}` which failed for missing status, triggering `step4_required=True`.

**Fix Applied:**
Added `offer_status` to step-appropriate defaults in test fixture (`conftest.py`):
- Step 4+: `offer_status = "sent"`
- Step 6+: `offer_status = "accepted"`
- Step 7: `offer_status = "accepted_final"`

---

## Test Results Summary

| Test Category | Passed | Failed | Status |
|---------------|--------|--------|--------|
| Date Change | 4/4 | 0 | ✅ |
| Room Change | 4/4 | 0 | ✅ |
| Participant Change | 4/4 | 0 | ✅ |
| Product Add | 8/8 | 0 | ✅ |
| Billing Capture | 4/4 | 0 | ✅ |

**Total: 109 E2E tests passing, 0 failed**

---

## Test Infrastructure Notes

- Tests use `E2ETestHarness` which calls `process_msg` directly
- AGENT_MODE=openai required for LLM detection
- Tests verify: draft messages, step transitions, fallback patterns, caller_step
