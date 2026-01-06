# SHORT-001: Date + Room Shortcut

**Test ID:** SHORT-001
**Category:** Shortcuts
**Flow:** 1 -> 4 (skips step 2 date confirmation loop)
**Pass Criteria:** Date and room confirmed in one message skips to offer

---

## Test Steps

### Send Combined Request

```
ACTION: Navigate, reset client
ACTION: Send email with date AND room:
---
Subject: Quick Booking - 14.02.2026

We need to book Room A for 25 people on 14.02.2026.
Setup: U-shape with projector.
Please send the offer.

test-short001@example.com
---

WAIT: Response appears
```

### Verify: Step Skipping

```
VERIFY: Response acknowledges:
  - Date (14.02.2026)
  - Room (Room A)
  - Capacity (25 people)
VERIFY: Response moves directly toward offer
VERIFY: No intermediate "confirm date?" loop
VERIFY: No separate "select room" step
VERIFY: Offer presented OR HIL task appears
```

### Verify Offer

```
IF HIL task appears:
  ACTION: Approve it
VERIFY: Offer contains:
  - Date: 14.02.2026
  - Room: Room A
  - Participants: 25
  - Pricing visible
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] All three captured in first message (date, room, capacity)
- [ ] Date confirmation step skipped
- [ ] Room selection step skipped
- [ ] Direct path to offer (Step 4)
