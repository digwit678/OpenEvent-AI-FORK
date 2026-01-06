# DET-002: Date Change from Step 3 - Room NOT Available

**Test ID:** DET-002
**Category:** Detours
**Flow:** 1 -> 2 -> 3 (detour to 2) -> 3 (re-select room) -> 4
**Pass Criteria:** Room re-selection required when room unavailable on new date

---

## Test Steps

### Setup: Get to Step 3 with Specific Room

```
ACTION: Navigate, reset client
ACTION: Send initial email for 30 people, request specific date
ACTION: Confirm date when offered
ACTION: Select Room A (or another room)
VERIFY: At Step 3 with room selected
```

### Trigger: Change to Date Where Room is Booked

```
ACTION: Send: "We need to change to a different date - how about 21.02.2026?"
WAIT: Response appears
```

### Verify: Room Re-Selection Required

```
VERIFY: Date change acknowledged
VERIFY: If room unavailable on new date:
  - Response indicates room not available
  - New room options presented
  - Client must select different room
VERIFY: NO fallback message
```

### Complete Room Selection and Offer

```
ACTION: Select new room: "Room B please"
WAIT: Response appears
ACTION: Request offer: "Send the offer"
WAIT: Offer appears
VERIFY: Offer shows new date AND new room
```

---

## Pass Criteria

- [ ] Room unavailability detected
- [ ] New room options presented
- [ ] Flow continues after new selection
- [ ] Offer reflects new date + room

---

## Test Run Results

### Run 1: 2024-12-24

**Setup: Get to Step 4 (Offer)**
- INPUT: "We need a room for 30 people on 07.02.2026. Coffee and projector needed."
- ACTUAL: System showed room options (A, B, F), selected Room A
- ACTUAL: System generated offer with Room A, CHF 725.00 total
- ✅ Successfully reached Step 4 (offer stage)

**Trigger: Date Change**
- INPUT: "We need to change to a different date - how about 21.02.2026?"
- EXPECTED: Date change processed, room availability re-checked on new date
- ACTUAL:
  ```
  [FALLBACK: api.routes.messages.send_message]
  Trigger: empty_workflow_reply
  Context: action=room_detour_capacity, draft_count=0, current_step=1
  ```
  Response: "Thanks for the update. I'll keep you posted as I gather the details."

**ISSUES FOUND:**
- 🔴 SAME BUG AS DET-001: FALLBACK triggered on date change
- 🔴 current_step=1 is wrong (should be 4)
- 🔴 action=room_detour_capacity detected but NOT executed
- 🔴 Generic fallback message instead of proper handling
- 🔴 Workflow appears broken after detour attempt

**OVERALL STATUS:** 🔴 FAIL - Same systematic detour bug as DET-001

**Root Cause Confirmed:**
Detour detection works (action=room_detour_capacity) but detour execution
fails completely, returning empty_workflow_reply. Step tracking corrupted to 1.
