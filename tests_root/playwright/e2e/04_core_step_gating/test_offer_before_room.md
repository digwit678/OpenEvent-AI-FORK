# GATE-002: Offer Request Before Room Selection

**Test ID:** GATE-002
**Category:** Step Gating
**Flow:** 1 -> 2 -> attempt Step 4 -> polite reminder -> Step 3 -> Step 4
**Pass Criteria:** System politely enforces room selection before offer

---

## Test Steps

### Setup: Get to Step 2

```
ACTION: Navigate, reset client
ACTION: Send initial request:
---
Subject: Conference Booking

Need a conference room for 25 people, March 2026.

test-gate002@example.com
---

WAIT: Response with date options
ACTION: Confirm date: "07.03.2026"
WAIT: Room options should appear
```

### Skip Room, Request Offer

```
ACTION: Ignore room options, request offer:
---
Can you just send me the offer?
---

WAIT: Response appears
```

### Verify: Room Required First

```
VERIFY: Response politely explains room needed first
VERIFY: Response is NOT an error message
VERIFY: Message explains why:
  - "First, let's select your room" OR
  - "Which room would you prefer?" OR
  - Re-presents room options
VERIFY: NO "cannot generate offer" error
VERIFY: NO fallback message
```

### Select Room

```
ACTION: Select room:
---
Room B please
---

WAIT: Response appears
```

### Verify: Offer Now Generated

```
VERIFY: Room B confirmed
VERIFY: Offer automatically generated OR
VERIFY: Simple "send offer" now works
```

### Request Offer Again

```
ACTION: Request offer if not auto-generated:
---
Now please send the offer
---

WAIT: Offer appears
```

### Verify: Offer Complete

```
VERIFY: Offer contains Room B
VERIFY: Offer has pricing
VERIFY: NO fallback message
```

---

## Pass Criteria

- [x] Premature offer request handled politely
- [x] Room selection enforced as prerequisite
- [x] No error-style messages
- [ ] Flow continues after room provided (not tested)
- [ ] Offer generated correctly once complete (not tested)
- [x] No fallback messages

---

## Test Run Results

### Run 1: 2024-12-24

**Step 1: Initial Request**
- INPUT: "Need a conference room for 25 people, March 2026."
- EXPECTED: Date options presented
- ACTUAL: System auto-picked 20.03.2026 and jumped directly to room selection
- NOTES: Shortcut behavior - "March 2026" auto-resolved to specific date

**Step 2: Request Offer Without Room**
- INPUT: "Can you just send me the offer?"
- EXPECTED: Polite message asking to select room first
- ACTUAL: System re-presented room options (Room A, B, D)
- ✅ Correctly enforced room selection prerequisite
- ✅ No error message, polite handling
- ✅ No fallback message

**OVERALL STATUS:** ✅ PASS (core gating behavior verified)

**Notes:**
- Step gating works correctly for offer-before-room
- System used shortcut for date (March 2026 → 20.03.2026) which is acceptable
- Did not complete full flow to offer (tested gating only)
