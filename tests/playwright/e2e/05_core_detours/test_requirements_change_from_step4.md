# DET-004: Requirements Change from Step 4

**Test ID:** DET-004
**Category:** Detours
**Flow:** 1 -> 2 -> 3 -> 4 (detour to 3) -> room re-eval -> 4
**Pass Criteria:** Capacity change triggers room re-evaluation

---

## Test Steps

### Setup: Get to Step 4

```
ACTION: Navigate, reset client
ACTION: Send email: 30 people, February 2026
ACTION: Confirm date, select room, get offer
VERIFY: At Step 4 with offer for 30 people
```

### Trigger: Capacity Change

```
ACTION: Send: "Actually we'll have 50 people instead of 30"
WAIT: Response appears
```

### Verify: Room Re-Evaluation

```
VERIFY: Capacity change detected
VERIFY: requirements_hash invalidated
VERIFY: Response indicates capacity change
VERIFY: If current room can't fit 50:
  - New room options presented
  - Must select suitable room
VERIFY: If current room fits 50:
  - May continue with same room
  - Pricing updated for 50 people
```

### Complete Flow to Offer

```
ACTION: If new room needed, select one
ACTION: Proceed to offer
VERIFY: Offer shows 50 people
VERIFY: Pricing reflects larger group
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Capacity change detected
- [ ] Room re-evaluated for new capacity
- [ ] Offer reflects new participant count
- [ ] Flow continues to Step 4

---

## Test Run Results

### Run 1: 2024-12-24

**Setup: Get to Step 4 (Offer)**
- INPUT: "We need a room for 30 people on 07.02.2026. Need projector."
- ACTUAL: Room options shown (A, B, F), selected Room A
- ACTUAL: Offer generated - Room A, CHF 500.00, 30 guests
- ✅ Successfully reached Step 4

**Trigger: Capacity Change**
- INPUT: "Actually we'll have 50 people instead of 30"
- EXPECTED: Room re-evaluation (Room A max capacity is 35, needs bigger room)
- ACTUAL:
  - System dropped back to DATE SELECTION (not room selection!)
  - Lost confirmed date (07.02.2026)
  - Shows dates in DEC 2025 instead of Feb 2026
  - Shows strange time slots "07:02–15:52"
  - "Wednesdays coming up: 24 Dec 2025, 31 Dec 2025, 07 Jan 2026..."
  - Completely forgot room preference and offer

**ISSUES FOUND:**
- 🔴 CONFIRMED DATE LOST: 07.02.2026 completely forgotten
- 🔴 WRONG DATES SHOWN: Dec 2025 dates (today) instead of Feb 2026
- 🔴 ROOM PREFERENCE LOST: Room A selection forgotten
- 🔴 OFFER DISCARDED: Entire offer context lost
- 🔴 WRONG STEP: Jumped back to Step 2 (dates) instead of Step 3 (rooms)
- ⚠️ Weird time format: "07:02–15:52" looks like extraction error

**OVERALL STATUS:** 🔴 FAIL - Requirements change causes full state corruption

**Root Cause Hypothesis:**
Unlike DET-001/DET-002 (FALLBACK error), this produces a response but:
- Detour logic resets too much state
- Date parsing may be extracting today's date from somewhere
- Step tracking lost (should go to Step 3 for room re-eval, not Step 2)
