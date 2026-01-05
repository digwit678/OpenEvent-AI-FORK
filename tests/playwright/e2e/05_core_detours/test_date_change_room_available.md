# DET-001: Date Change from Step 3 - Room Still Available

**Test ID:** DET-001
**Category:** Detours
**Flow:** 1 -> 2 -> 3 (detour to 2) -> 3 (fast-skip) -> 4
**Pass Criteria:** Room selection NOT repeated when room still available on new date

---

## Test Steps

### Setup: Get to Step 3 (Room Selection)

```
ACTION: Navigate to http://localhost:3000, reset client
ACTION: Send initial email:
---
Subject: Workshop - February 2026
30 people workshop in February 2026.
Need projector and coffee.
test-det001@example.com
---

WAIT: Date options shown
ACTION: Send: "07.02.2026 works for us"
WAIT: Room options shown
VERIFY: At Step 3 (room selection)
```

### Trigger: Date Change at Step 3

```
ACTION: Send: "Actually, can we change to 14.02.2026 instead?"
WAIT: Response appears
```

### Verify: Detour Behavior

```
VERIFY: Response acknowledges date change
VERIFY: Response shows new date (14.02.2026)
VERIFY: Room is still available check happens
VERIFY: If room still available on new date:
  - Response does NOT ask for room selection again
  - Response continues toward offer OR
  - Response confirms room still available
VERIFY: NO fallback message
```

### Continue to Offer

```
ACTION: If room confirmed, send: "Please proceed with the offer"
WAIT: Response appears
VERIFY: Offer generated with new date (14.02.2026)
VERIFY: Same room as before (unless unavailable)
```

---

## Pass Criteria

- [ ] Date change detected and processed
- [ ] No repeated room selection (fast-skip worked)
- [ ] Flow continues to Step 4 (offer)
- [ ] No fallback messages

---

## Test Run Results

### Run 1: 2024-12-24

**Setup: Get to Step 3**
- INPUT: "We are planning an event for 30 people in February 2026."
- ACTUAL: System auto-picked 20.02.2026, jumped to room selection (Room A available)
- ✅ Successfully reached Step 3

**Room Selection**
- INPUT: "Room A please"
- ACTUAL: System asked about catering/add-ons
- ✅ Room selected, moving toward Step 4

**Trigger: Date Change**
- INPUT: "Actually, can we change to 14.02.2026 instead?"
- EXPECTED: Date change processed, room availability checked, continue to offer
- ACTUAL:
  ```
  [FALLBACK: api.routes.messages.send_message]
  Trigger: empty_workflow_reply
  Context: action=room_detour_capacity, draft_count=0, current_step=1
  ```
  Response: "Thanks for the update. I'll keep you posted as I gather the details."

**ISSUES FOUND:**
- 🔴 FALLBACK triggered - system couldn't handle date change detour
- 🔴 current_step=1 is wrong (should be 3 or 4)
- 🔴 action=room_detour_capacity detected but not processed
- 🔴 Generic fallback message sent instead of proper handling
- 🔴 Workflow appears broken after detour attempt

**OVERALL STATUS:** 🔴 FAIL - Critical bug in detour handling

**Root Cause Hypothesis:**
Detour detection works (action=room_detour_capacity) but the detour execution fails,
resulting in empty_workflow_reply fallback. Step tracking may also be corrupted.
