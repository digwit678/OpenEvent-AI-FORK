# Test Matrix: Detection Types and Flow Coverage

**Generated:** 2025-11-27
**Purpose:** Define concrete test IDs for each detection type, workflow flow, and known regression.

---

## Test ID Convention

```
DET_<category>_<scenario>_<number>
FLOW_<step_range>_<scenario>_<number>
REG_<bug_id>_<number>
```

---

## 1. Q&A Detection Tests

### General Q&A (Pre-Step Questions)

| Test ID | Scenario | Input | Expected Detection | Notes |
|---------|----------|-------|-------------------|-------|
| `DET_QNA_001` | Room features question | "Do your rooms have HDMI?" | `is_general=True`, `secondary=["rooms_by_feature"]` | Should not block step flow |
| `DET_QNA_002` | Availability question | "Which rooms are free on Saturdays in February for 30 people?" | `is_general=True`, vague_month=february | General Q&A path |
| `DET_QNA_003` | Catering question | "What menus do you offer?" | `secondary=["catering_for"]` | Q&A, not intent change |
| `DET_QNA_004` | Mixed step + QNA | "December 10-11 for 22 ppl. Do rooms have HDMI?" | `primary=date_confirmation`, `secondary=["rooms_by_feature"]` | Step takes priority; Q&A pre-block |
| `DET_QNA_005` | Site visit question | "Can we arrange a tour of the venue?" | `secondary=["site_visit_overview"]` | Q&A category |
| `DET_QNA_006` | Parking policy | "Where can guests park?" | `secondary=["parking_policy"]` | Q&A category |

### Fallback Guard Tests

| Test ID | Scenario | Assertion |
|---------|----------|-----------|
| `DET_QNA_FALLBACK_001` | General Q&A must NOT return stub | Response must NOT contain "no specific information available" |
| `DET_QNA_FALLBACK_002` | Mixed query must NOT return stub | Response must NOT contain "no specific information available" |
| `DET_QNA_FALLBACK_003` | Room features query must return actual data | Response must contain room names or feature info |

---

## 2. Special Manager Request Detection

| Test ID | Scenario | Input | Expected Detection |
|---------|----------|-------|-------------------|
| `DET_MGR_001` | Explicit escalation | "I need to speak with a manager" | `_looks_like_manager_request=True` |
| `DET_MGR_002` | Human request | "Can I talk to a human?" | `_looks_like_manager_request=True` |
| `DET_MGR_003` | Connect request | "Please connect me with someone" | `_looks_like_manager_request=True` |
| `DET_MGR_004` | Escalation keyword | "I want to escalate this" | `_looks_like_manager_request=True` |
| `DET_MGR_005` | NOT manager request | "The manager approved the budget" | `_looks_like_manager_request=False` |
| `DET_MGR_006` | NOT manager request | "Please send the offer to my manager" | `_looks_like_manager_request=False` |

---

## 3. Detour Detection Tests

### Date Change Detours

| Test ID | Scenario | Current State | Input | Expected |
|---------|----------|---------------|-------|----------|
| `DET_DETOUR_DATE_001` | Change confirmed date | `date_confirmed=True, current_step=4` | "Can we change the date to March 20?" | `ChangeType.DATE`, `next_step=2` |
| `DET_DETOUR_DATE_002` | Reschedule request | `date_confirmed=True, current_step=5` | "We need to reschedule to next month" | `ChangeType.DATE`, `next_step=2` |
| `DET_DETOUR_DATE_003` | Correction marker | `date_confirmed=True` | "Actually, let's do April 15 instead" | `ChangeType.DATE`, `next_step=2` |

### Room Change Detours

| Test ID | Scenario | Current State | Input | Expected |
|---------|----------|---------------|-------|----------|
| `DET_DETOUR_ROOM_001` | Change locked room | `locked_room_id="Room A"` | "Can we switch to Room B?" | `ChangeType.ROOM`, `next_step=3` |
| `DET_DETOUR_ROOM_002` | Bigger room request | `locked_room_id="Room A"` | "We need a bigger room" | `ChangeType.ROOM`, `next_step=3` |
| `DET_DETOUR_ROOM_003` | Room preference change | Step 4 | "Room C would work better" | `ChangeType.ROOM`, `next_step=3` |

### Requirements/Guests Change Detours

| Test ID | Scenario | Current State | Input | Expected |
|---------|----------|---------------|-------|----------|
| `DET_DETOUR_REQ_001` | Participants increase | `participants=24, current_step=4` | "Actually we'll have 36 people" | `ChangeType.REQUIREMENTS`, `next_step=3` |
| `DET_DETOUR_REQ_002` | Layout change | `seating_layout="theatre"` | "Can we switch to banquet seating?" | `ChangeType.REQUIREMENTS`, `next_step=3` |
| `DET_DETOUR_REQ_003` | Duration change | Step 4 | "We need to extend to 23:00" | `ChangeType.REQUIREMENTS`, `next_step=3` |
| `DET_DETOUR_REQ_004` | No change (same value) | `participants=24` | "We still have 24 people" | `needs_reeval=False` (hash match) |

### Product Change (No Detour)

| Test ID | Scenario | Current State | Input | Expected |
|---------|----------|---------------|-------|----------|
| `DET_DETOUR_PROD_001` | Add product | Step 4 | "Add a wireless microphone" | `ChangeType.PRODUCTS`, `next_step=4` |
| `DET_DETOUR_PROD_002` | Remove product | Step 4 | "Remove the coffee break" | `ChangeType.PRODUCTS`, `next_step=4` |
| `DET_DETOUR_PROD_003` | Menu change | Step 4 | "Switch to the Garden Trio menu" | `ChangeType.PRODUCTS`, `next_step=4` |

---

## 4. Confirmation/Acceptance Detection

| Test ID | Scenario | Input | Expected Intent |
|---------|----------|-------|-----------------|
| `DET_ACCEPT_001` | Simple acceptance | "Yes, that's fine" | `is_acceptance=True` |
| `DET_ACCEPT_002` | Proceed confirmation | "Please proceed" | `is_acceptance=True` |
| `DET_ACCEPT_003` | OK acceptance | "OK, go ahead" | `is_acceptance=True` |
| `DET_ACCEPT_004` | Curly apostrophe | "that's fine" (curly quote) | `is_acceptance=True` (normalized) |
| `DET_ACCEPT_005` | Approved | "Approved, please send" | `is_acceptance=True` |
| `DET_ACCEPT_006` | NOT acceptance (question) | "Is this the final offer?" | `is_acceptance=False` |
| `DET_ACCEPT_007` | NOT acceptance (change) | "Can you adjust the price?" | `is_acceptance=False`, detect counter |
| `DET_ACCEPT_008` | Date confirmation | "2025-12-10 18:00-22:00" (bare) | `_message_signals_confirmation=True` |
| `DET_ACCEPT_009` | Date confirmation quoted | Quoted thread + "2025-12-10 18:00-22:00" | `_message_signals_confirmation=True` |

---

## 5. Shortcut Detection Tests

| Test ID | Scenario | Step | Input | Expected Capture |
|---------|----------|------|-------|-----------------|
| `DET_SHORT_001` | Capacity at intake | Step 1 | "Event for 30 people" | `shortcuts.capacity=30` |
| `DET_SHORT_002` | Date at intake | Step 1 | "Thinking December 10" | `shortcuts.date="2025-12-10"` |
| `DET_SHORT_003` | Products at intake | Step 1 | "We'll need a projector" | `wish_products=["projector"]` |
| `DET_SHORT_004` | Multiple shortcuts | Step 1 | "30 people on Dec 10 with projector" | All captured |
| `DET_SHORT_005` | Invalid shortcut ignored | Step 1 | "Negative -5 people" | NOT captured (invalid) |
| `DET_SHORT_006` | Shortcut reuse at step | Step 3 | (capacity already captured) | No re-ask for capacity |

---

## 6. User Preferences / Room Sorting

| Test ID | Scenario | Preferences | Expected Sort |
|---------|----------|-------------|---------------|
| `DET_PREF_001` | Menu preference ranking | `wish_products=["wine"]` | Rooms with wine ranked higher |
| `DET_PREF_002` | Capacity sort | `participants=30` | Rooms fitting 30+ first |
| `DET_PREF_003` | Product availability | `wish_products=["projector"]` | Rooms with projector ranked higher |
| `DET_PREF_004` | Combined preferences | Multiple preferences | Weighted ranking |

---

## 7. Gatekeeping Tests (Billing + Deposit)

### Billing Validation

| Test ID | Scenario | State | Input | Expected |
|---------|----------|-------|-------|----------|
| `DET_GATE_BILL_001` | Complete billing | All fields | N/A | `billing_complete=True` |
| `DET_GATE_BILL_002` | Missing street | No street | N/A | `billing_complete=False`, prompt for street |
| `DET_GATE_BILL_003` | Missing postal | No postal code | N/A | `billing_complete=False`, prompt for postal |
| `DET_GATE_BILL_004` | Acceptance without billing | No billing | "Approved" | Prompt for billing, don't confirm |
| `DET_GATE_BILL_005` | Billing fragment detection | N/A | "Postal code: 8000" | Detected as billing update |
| `DET_GATE_BILL_006` | Room name not billing | N/A | "Room E" | NOT detected as billing |

### Deposit Validation

| Test ID | Scenario | State | Input | Expected |
|---------|----------|-------|-------|----------|
| `DET_GATE_DEP_001` | Deposit required policy | Step 7 | N/A | Check deposit_required flag |
| `DET_GATE_DEP_002` | Deposit paid detection | Step 7 | "Deposit has been paid" | `deposit_paid=True` |
| `DET_GATE_DEP_003` | Confirmation without deposit | `deposit_required=True` | "Please confirm" | Block, request deposit |

---

## 8. Hybrid Message Tests

| Test ID | Scenario | Input | Expected |
|---------|----------|-------|----------|
| `DET_HYBRID_001` | Date + Q&A | "December 10 for 22 ppl. Do rooms have HDMI?" | Date processed, Q&A in pre-block |
| `DET_HYBRID_002` | Room + Menu | "Room B with Seasonal Garden Trio" | Room locked, menu added as line item |
| `DET_HYBRID_003` | Billing + Acceptance | "ACME AG, Zurich. Please proceed." | Billing captured, then acceptance processed |
| `DET_HYBRID_004` | Multiple Q&A topics | "What menus and equipment available?" | Multiple Q&A categories |
| `DET_HYBRID_005` | Step + Products | "Confirm date, and add coffee break" | Date confirmed, product added |

---

## 9. Happy-Path Flow Test: Steps 1-4

### FLOW_1TO4_HAPPY_001: Complete Intake to Offer

| Turn | Input | Expected State | Key Assertions |
|------|-------|----------------|----------------|
| 1 | "I'd like to book a workshop for 25 people on December 15, 2025, 14:00-18:00" | Step 1 complete | `event_id` created, `email` prompt if missing |
| 2 | "client@example.com" | Step 1 → Step 2 | `email` captured, advance to date |
| 3 | (System proposes dates) | Step 2 awaiting | `date_confirmed=False` |
| 4 | "December 15 works" | Step 2 → Step 3 | `date_confirmed=True`, `chosen_date` set |
| 5 | (System presents rooms) | Step 3 awaiting | Room options shown |
| 6 | "Room A please" | Step 3 → Step 4 | `locked_room_id="Room A"`, `room_eval_hash` set |
| 7 | (System presents offer draft) | Step 4 awaiting HIL | Offer draft with footer |
| 8 | HIL Approve | Offer sent | `thread_state="Awaiting Client"` |

### Key Assertions for FLOW_1TO4_HAPPY_001

1. **No fallback messages** - Response must NOT contain "no specific information available" or generic stubs
2. **Correct step progression** - `current_step` advances correctly
3. **Hash consistency** - `requirements_hash` computed at intake, `room_eval_hash` matches after lock
4. **HIL gates respected** - Drafts require approval before client-facing send
5. **Footer contract** - Every outbound includes `Step: X · Next: Y · State: Z`
6. **Status lifecycle** - `event.status = "Lead"` at offer creation

---

## 10. Regression Tests (Linked to TEAM_GUIDE Bugs)

| Test ID | Bug | Scenario | Key Assertion |
|---------|-----|----------|---------------|
| `REG_PRODUCT_DUP_001` | Product Additions Causing Duplicates | Add product via explicit request | Quantity +1, not +2 |
| `REG_ACCEPT_STUCK_001` | Offer Acceptance Stuck | "that's fine" acceptance | Reaches Step 5, HIL task created |
| `REG_HIL_DUP_001` | Duplicate HIL sends | Re-acceptance while waiting | No duplicate tasks/drafts |
| `REG_DATE_MONTH_001` | Spurious unavailable apologies | "February Saturdays" | No apology for unmentioned dates |
| `REG_QUOTE_CONF_001` | Quoted confirmation triggering Q&A | Quoted thread + bare date | `is_general=False`, Step 3 autoloads |
| `REG_ROOM_REPEAT_001` | Room choice repeats | "Room E" reply | No duplicate room list, no manual review |
| `REG_BILL_ROOM_001` | Room label as billing | "Room E" | NOT saved as billing address |

---

## 11. Anti-Fallback Assertions

**Every test must include:**

```python
# Assert no legacy fallback messages
FALLBACK_PATTERNS = [
    "no specific information available",
    "sorry, cannot handle",
    "unable to process",
    "I don't understand",
]

def assert_no_fallback(response_body: str):
    lowered = response_body.lower()
    for pattern in FALLBACK_PATTERNS:
        assert pattern not in lowered, f"Fallback detected: {pattern}"
```

---

## Implementation Priority

### Phase 1: Core Detection (New Files)

1. `backend/tests/detection/test_qna_detection.py` - DET_QNA_*
2. `backend/tests/detection/test_manager_request.py` - DET_MGR_*
3. `backend/tests/detection/test_acceptance.py` - DET_ACCEPT_*

### Phase 2: Detours and Changes

4. `backend/tests/detection/test_detour_date.py` - DET_DETOUR_DATE_*
5. `backend/tests/detection/test_detour_room.py` - DET_DETOUR_ROOM_*
6. `backend/tests/detection/test_detour_requirements.py` - DET_DETOUR_REQ_*

### Phase 3: Gatekeeping

7. `backend/tests/detection/test_billing_gate.py` - DET_GATE_BILL_*
8. `backend/tests/detection/test_deposit_gate.py` - DET_GATE_DEP_*

### Phase 4: Integration

9. `backend/tests/flow/test_happy_path_step1_to_4.py` - FLOW_1TO4_*
10. `backend/tests/regression/test_team_guide_bugs.py` - REG_*

---

## References

- `tests/TEST_INVENTORY.md` - Current test coverage
- `tests/TEST_REORG_PLAN.md` - Reorganization plan
- `docs/guides/TEAM_GUIDE.md` - Known bugs and fixes
- `backend/llm/intent_classifier.py` - Intent detection
- `backend/workflows/change_propagation.py` - Change routing
- `backend/workflows/nlu/general_qna_classifier.py` - Q&A detection
