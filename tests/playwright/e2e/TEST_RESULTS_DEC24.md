# E2E Test Results - December 24-25, 2025

## Test Summary

| Tier | Tests Run | Passed | Failed |
|------|-----------|--------|--------|
| CRITICAL (01) | 3 | 3 | 0 |
| CORE - Step Gating (04) | 2 | 2 | 0 |
| CORE - Detours (05) | 5 | 5 | 0 |
| CORE - Full Flow (FLOW) | 2 | 2 | 0 |
| **Total** | **12** | **12** | **0** |

### December 25 Updates
**All 12 tests now PASSING!** 🎉

**GATE-001 Fix (preferred room ranking):**
- Increased `preferred_bonus` from 10→30 (sorting.py)
- Removed re-sorting that overrode ranking (step3_handler.py)
- Added LLM instruction for room ordering (verbalizer_agent.py)
- Simplified `_select_room()` to trust ranking (step3_handler.py)

**All detour tests now PASSING** after bug fixes:
- Fixed room change time confirmation bug (step2_handler.py)
- Fixed date change room lock preservation (step1_handler.py)
- Fixed capacity exceeds all rooms handling (step3_handler.py, ranking.py)

**Full flow tests PASSING**:
- FLOW-001: Complete happy path (intake → site visit message) ✅
- GATE-001: Room Before Date (intake → Room A preferred → site visit) ✅

---

## Tier 1: CRITICAL - Database Tests (01_critical_database)

### DB-001: Event Creation ✅ PASS
- Event persisted to `events_database.json`
- `event_id`, `created_at`, `requirements` all present
- Correct `number_of_participants: 30`

### DB-002: Room Lock ✅ PASS
- `locked_room_id` set correctly after room selection
- `room_eval_hash` matches `requirements_hash`

### DB-003: HIL Visibility ✅ PASS
- HIL task appeared in "Manager Tasks" section
- Approve/Reject buttons functional

---

## Tier 2: CORE - Step Gating (04_core_step_gating)

### GATE-001: Room Before Date ✅ PASS
**Scenario:** Client requests Room A without specifying date

**Fixed (Dec 25):**
- Increased `preferred_bonus` from 10→30 to overcome status weight difference
- Removed re-sorting that overrode preferred room ranking
- Added LLM instruction to respect `recommended_room` in room ordering
- Simplified `_select_room()` to trust ranking order

**Result:** System correctly asks for date, remembers Room A preference, recommends Room A when rooms are presented

### GATE-002: Offer Before Room ✅ PASS
**Scenario:** Client tries to get offer before selecting room

**Result:** System correctly re-presented room options, enforcing step order

---

## Tier 2: CORE - Detours (05_core_detours)

### DET-001: Date Change from Step 3 ✅ PASS (Fixed Dec 25)
**Scenario:** Client at room selection stage requests date change

**Result:** Correctly routes to Step 2, preserves `locked_room_id` for fast-skip if room still available on new date.

**Fixes Applied:**
- `step1_handler.py`: Only clears `room_eval_hash`, keeps `locked_room_id` for DATE changes
- `step2_handler.py`: Skips time confirmation when room is already locked (detour case)

### DET-002: Date Change Room Unavailable ✅ PASS (Fixed Dec 25)
**Scenario:** Client changes to date where room is unavailable

**Result:** When locked room has "Confirmed" status on new date:
- Correctly clears `locked_room_id`
- Re-presents room options (Room B, Room C)
- No time confirmation prompt

**Test Conditions:**
- Created blocking event with `status="Confirmed"` on target date
- Verified room status shows as "unavailable" in Step 3

### DET-003: Room Change from Step 4 ✅ PASS (Fixed Dec 25)
**Scenario:** Client at offer stage requests different room

**Result:** Routes directly to Step 3, no time confirmation prompt.

**Fixes Applied:**
- `step2_handler.py`: When `locked_room_id` exists (detour case), skips `_handle_partial_confirmation`
- Uses default times (14:00-22:00) if time unspecified, proceeds to room selection

### DET-004: Requirements Change from Step 4 ✅ PASS
**Scenario:** Client at offer stage changes capacity (30 → 50 people)

**Result:** Correctly routes to Step 3 with updated capacity requirements.

**Detailed Test (Dec 25):**
1. Start with 30 people, select Room A (max 40)
2. Change to 50 people → Routes to Step 3 ✅
3. Room A now shown as "Option" (not ideal fit) ✅
4. Larger rooms (B, C, E) prioritized ✅

### DET-004b: Capacity Exceeds All Rooms ✅ PASS (Fixed Dec 25)
**Scenario:** Client changes capacity to 150 people (max room is 120)

**Result:** System now properly handles capacity overflow.

**Fix Applied:**
1. Added `any_room_fits_capacity()` check in Step 3
2. Created `_handle_capacity_exceeded()` with:
   - Clear message: "Our largest venue, Room E, accommodates up to 120 guests"
   - Three alternatives offered (reduce, split, external)
   - Action buttons for quick resolution

**Test Flow:**
- 150 guests → "Capacity exceeded" message ✅
- Shows max capacity (120) and alternatives ✅
- Client reduces to 100 → Shows Room E as best fit ✅
- Flow continues normally ✅

**Files Modified:** `backend/rooms/ranking.py`, `backend/workflows/steps/step3_room_availability/trigger/step3_handler.py`

---

## Root Causes Identified (All Fixed Dec 25)

### Issue A: ✅ FIXED - Room Lock Cleared on Date Change
**Location:** `backend/workflows/steps/step1_intake/trigger/step1_handler.py` lines 1177-1204

**Problem:** For DATE changes routing to Step 2, code was clearing `locked_room_id` unnecessarily.

**Fix:** Only clear `room_eval_hash` for date changes, keep `locked_room_id` so Step 3 can fast-skip if room is still available on new date.

### Issue B: ✅ FIXED - Time Confirmation During Detour
**Location:** `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py` lines 1009-1029

**Problem:** When `window.partial` (date without time), always asked for time confirmation.

**Fix:** When room is already locked (detour case), skip time confirmation and use default times (14:00-22:00). Time is handled in Step 3 (room availability), not Step 2.

### Issue C: ✅ FIXED (Previous Session) - Date Corruption to TODAY
This was fixed in a previous session by properly preserving `chosen_date` during detours.

---

## Files Fixed (Dec 25)

| File | Lines | Fix Applied |
|------|-------|-------------|
| `backend/workflows/steps/step1_intake/trigger/step1_handler.py` | 1177-1204 | ✅ Room lock preservation for DATE changes |
| `backend/workflows/steps/step2_date_confirmation/trigger/step2_handler.py` | 1009-1029 | ✅ Skip time confirmation when room locked |

---

## Full Flow Test Results (Dec 25)

### FLOW-001: Full Happy Path Step 1 → 7 ✅ PASS

**Test:** Complete booking flow from intake to site visit message

**Steps Executed:**
1. **Intake**: "Room for 30 people on 14.02.2026. Projector needed."
   - Shortcuts captured: date, capacity, projector requirement
   - Skipped to Step 3 (room availability)

2. **Room Selection**: "Room A please"
   - Room A locked (`locked_room_id` set)
   - Advanced to Step 4 (products)

3. **Products**: "No extras needed, please proceed"
   - Advanced to offer presentation

4. **Offer Acceptance**: "Yes, I accept the offer"
   - Billing gate triggered (missing billing address)
   - Prompted for billing

5. **Billing Capture**: "Test Company AG, Teststrasse 123, 8000 Zurich, Switzerland"
   - Billing captured, deposit gate triggered
   - Deposit required: CHF 150.00

6. **Deposit Payment**: (via `/api/event/deposit/pay`)
   - Deposit marked paid
   - HIL task created for final approval

7. **HIL Approval**: (via `/api/tasks/{id}/approve`)
   - **Result**: Site visit message sent!
   - Response: "Let's continue with site visit bookings. Do you have any preferred dates or times?"

**Key Validations:**
- ✅ All shortcuts captured at intake
- ✅ Billing gate enforced before confirmation
- ✅ Deposit gate enforced before HIL
- ✅ HIL task created correctly
- ✅ Site visit message delivered

### FLOW-002: Capacity Exceeded Recovery → Site Visit ✅ PASS

**Test:** Capacity overflow handling with recovery to full booking flow

**Steps Executed:**
1. **Intake (Capacity Overflow)**: "150 people on 25.02.2026. Projector needed."
   - Capacity exceeds all rooms (max 120)
   - `_handle_capacity_exceeded()` triggered
   - Message shows max capacity (120) and three alternatives

2. **Capacity Reduction**: "We will reduce to 100 guests instead."
   - System correctly updates requirements
   - Routes back to Step 3 (room availability)
   - Room E shown as best fit (capacity 120)

3. **Room Selection**: "Room E please"
   - Room E locked
   - Advanced to Step 4 (products)

4. **Products**: "No extras needed, please proceed with the offer."
   - Advanced to offer presentation
   - Offer: CHF 1,650 (Room E)

5. **Offer Acceptance**: "Yes, I accept the offer"
   - Billing gate triggered
   - Prompted for billing address

6. **Billing Capture**: "E2E Test Company GmbH, Testweg 99, 8000 Zurich, Switzerland"
   - Billing captured
   - Deposit gate triggered (CHF 495)

7. **Deposit Payment**: (via `/api/event/deposit/pay`)
   - Deposit marked paid
   - HIL task created for final approval

8. **HIL Approval**: (via `/api/tasks/{id}/approve`)
   - **Result**: Site visit message sent!
   - Response: "Let's continue with site visit bookings. Do you have any preferred dates or times?"

**Key Validations:**
- ✅ Capacity exceeded message shows max (120) and alternatives
- ✅ Recovery from capacity overflow works correctly
- ✅ Room E (largest) correctly offered for 100 guests
- ✅ Full billing → deposit → HIL → site visit flow works
- ✅ Verbalizer formats capacity exceeded message professionally

---

## Tests Remaining

### Priority 1: Core Flow Extensions
- [x] **FLOW-001**: Full happy path Step 1 → 7 ✅ PASS (Dec 25)
- [x] **FLOW-002**: Capacity exceeded recovery → Site Visit ✅ PASS (Dec 25)
- [ ] **DET-005**: Date Change from Step 5 (negotiation phase)

### Priority 2: Shortcut Tests (06_core_shortcuts)
- [x] Multi-variable shortcut capture at intake ✅ (verified in FLOW-001)
- [ ] Shortcut preservation through detours

### Priority 3: Feature Tests (07-10)
- [x] Billing flow end-to-end ✅ (verified in FLOW-001)
- [x] Deposit flow end-to-end ✅ (verified in FLOW-001)
- [ ] Site visit scheduling (client response handling)
- [x] HIL task approval flow ✅ (verified in FLOW-001)

### Priority 4: Input Handling (11-13)
- [ ] Multilingual input (German/English)
- [ ] Edge case date formats
- [ ] Invalid input handling

### Priority 5: UX Tests (14-15)
- [ ] Error message clarity
- [ ] Response consistency
