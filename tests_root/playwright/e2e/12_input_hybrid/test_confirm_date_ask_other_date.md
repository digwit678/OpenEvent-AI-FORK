# HYB-002: Confirm One Date, Ask About Another

**Test ID:** HYB-002
**Category:** Hybrid Messages
**Flow:** Complex hybrid - confirmation + dynamic Q&A about different date
**Pass Criteria:** Both date contexts handled correctly without confusion

---

## Test Steps

### Setup: Get to Date Confirmation

```
ACTION: Navigate, reset client
ACTION: Send initial request:
---
Subject: Workshop Inquiry

Planning a workshop for 25 people in spring 2026.

test-hyb002@example.com
---

WAIT: Response with date options (likely May dates)
```

### Send Complex Hybrid

```
ACTION: Send message confirming one date, asking about another:
---
May 1st works for us. But we might also need a second session - what's available in late February?
---

WAIT: Response appears
```

### Verify: Dual Date Handling

```
VERIFY: Response correctly handles BOTH:
  1. CONFIRMATION: May 1st (01.05.2026) confirmed for booking
     - Workflow state updated with May date
     - Moving toward room selection for May event

  2. Q&A: February availability answered
     - Lists available dates in late February
     - Does NOT change the booking date
     - Clearly framed as informational

VERIFY: No confusion between the two dates
VERIFY: Booking continues with May 1st
VERIFY: February info is just Q&A, not a booking change
VERIFY: NO fallback message
```

### Verify: Workflow State Correct

```
ACTION: Continue with room selection
VERIFY: Room options are for May 1st (not February)
VERIFY: Date shown is 01.05.2026
```

---

## Alternative Test: Accept Offer, Ask About Different Month

```
ACTION: Navigate, reset client
ACTION: Complete flow to offer stage (any date)
ACTION: Send hybrid acceptance + question:
---
I accept this offer for March 7th.
By the way, what dates are available in June if I need to book another event?
---

WAIT: Response appears
```

### Verify: Acceptance + Q&A Separated

```
VERIFY: Offer accepted for March 7th (workflow action)
VERIFY: June availability provided (Q&A)
VERIFY: Current booking NOT changed to June
VERIFY: Billing/deposit flow continues for March event
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Confirmation date correctly identified
- [ ] Q&A date correctly identified as informational
- [ ] No date confusion between contexts
- [ ] Workflow proceeds with confirmed date
- [ ] Q&A about other dates doesn't affect booking
- [ ] Complex intent parsing succeeds
- [ ] No fallback messages
