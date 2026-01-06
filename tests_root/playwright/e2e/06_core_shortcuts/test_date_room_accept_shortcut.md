# SHORT-002: Date + Room + Accept Shortcut

**Test ID:** SHORT-002
**Category:** Shortcuts
**Flow:** 1 -> 5 (skips steps 2, 3, 4 via shortcut chain)
**Pass Criteria:** Single message with date, room, and acceptance skips directly to post-acceptance

---

## Test Steps

### Send Combined Request with Acceptance

```
ACTION: Navigate, reset client
ACTION: Send email with date, room, AND acceptance:
---
Subject: Confirmed Booking - 21.02.2026

We confirm Room B for 20 participants on 21.02.2026.
Setup: Theater style with microphone.
I accept the standard rates and terms.

Please proceed with the booking.

test-short002@example.com
---

WAIT: Response appears
```

### Verify: Maximum Step Skipping

```
VERIFY: Response acknowledges:
  - Date (21.02.2026)
  - Room (Room B)
  - Capacity (20 people)
  - Acceptance intent
VERIFY: System processes shortcut chain:
  - Skips Step 2 (date already confirmed in message)
  - Skips Step 3 (room already specified)
  - Skips Step 4 (acceptance implies offer terms)
VERIFY: Response moves toward Step 5 (post-acceptance)
VERIFY: NO intermediate confirmation loops
```

### Verify: Post-Acceptance Flow

```
VERIFY: System either:
  - Requests billing information (if not provided), OR
  - Requests deposit, OR
  - Moves toward final confirmation
VERIFY: Offer hash created
VERIFY: Event status updated
VERIFY: NO fallback message
```

### Complete Remaining Steps

```
IF billing requested:
  ACTION: Provide billing: "Billing: Test Company, Main Street 1, 8000 Zurich"
  WAIT: Response

IF deposit requested:
  ACTION: Click "Pay Deposit" or confirm payment
  WAIT: Response

VERIFY: Flow progresses toward site visit / confirmation
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Date, room, and acceptance captured in one message
- [ ] Step 2 (date confirmation) skipped
- [ ] Step 3 (room selection) skipped
- [ ] Step 4 (offer presentation) condensed/skipped
- [ ] Direct path to Step 5 (post-acceptance flow)
- [ ] Event created with correct details
