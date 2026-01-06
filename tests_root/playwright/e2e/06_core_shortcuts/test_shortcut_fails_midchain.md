# SHORT-003: Shortcut Fails Mid-Chain

**Test ID:** SHORT-003
**Category:** Shortcuts
**Flow:** 1 -> attempts shortcut -> stops at appropriate step
**Pass Criteria:** Invalid room stops shortcut chain gracefully

---

## Test Steps

### Send Request with Invalid Room

```
ACTION: Navigate, reset client
ACTION: Send email with date AND invalid room:
---
Subject: Event Booking - 28.02.2026

We'd like to book the "Executive Suite" for 30 people on 28.02.2026.
Full day conference with catering.

test-short003@example.com
---

WAIT: Response appears
```

### Verify: Shortcut Chain Stops Appropriately

```
VERIFY: Date captured (28.02.2026)
VERIFY: Capacity captured (30 people)
VERIFY: Room NOT recognized (no "Executive Suite" in database)
VERIFY: Response either:
  - Asks for clarification about room, OR
  - Presents available room options, OR
  - Continues to Step 3 (room selection)
VERIFY: Shortcut chain did NOT skip to offer
VERIFY: NO fallback message
```

### Continue with Valid Room Selection

```
ACTION: Select valid room: "Room A please"
WAIT: Response appears

VERIFY: Room selection acknowledged
VERIFY: Flow continues toward offer
```

### Complete to Offer

```
ACTION: Request offer if not automatic: "Please send the offer"
WAIT: Offer appears

VERIFY: Offer contains:
  - Date: 28.02.2026
  - Room: Room A (the valid selection)
  - Participants: 30
VERIFY: NO fallback message
```

---

## Alternative Test: Room Unavailable on Date

### Setup

```
ACTION: Navigate, reset client
ACTION: Send email with valid room that's unavailable on specified date:
---
Subject: Conference - 21.02.2026

Book Room A for 25 people on 21.02.2026.
(Note: Test assumes Room A is unavailable on this date)

test-short003b@example.com
---

WAIT: Response appears
```

### Verify: Graceful Handling

```
VERIFY: System detects room unavailability
VERIFY: Response indicates room not available on that date
VERIFY: Alternative options presented:
  - Different rooms available on 21.02.2026, OR
  - Different dates when Room A is available
VERIFY: Shortcut chain stopped at room availability check
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Invalid/unavailable room detected
- [ ] Shortcut chain stops at appropriate point
- [ ] Clear feedback to client about issue
- [ ] Flow continues after valid room provided
- [ ] Final offer reflects corrected information
- [ ] No fallback messages throughout
