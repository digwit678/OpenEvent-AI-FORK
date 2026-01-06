# HYB-001: Workflow Confirmation + Q&A in One Message

**Test ID:** HYB-001
**Category:** Hybrid Messages
**Flow:** Step 2 with embedded Q&A
**Pass Criteria:** Workflow action processed FIRST, Q&A answered SECOND

---

## Test Steps

### Setup: Get to Date Confirmation

```
ACTION: Navigate, reset client
ACTION: Send initial booking request:
---
Subject: Birthday Party Booking

Looking to book a room for 20 people in February 2026.
Birthday celebration.

test-hyb001@example.com
---

WAIT: Response with date options
```

### Send Hybrid Message

```
ACTION: Send message with confirmation + question:
---
Yes, 07.02.2026 works. Do you have parking available?
---

WAIT: Response appears
```

### Verify: Response Order

```
VERIFY: Response structure:
  1. FIRST: Workflow acknowledgment
     - Date confirmation processed (07.02.2026)
     - Moving toward room selection
  2. SECOND: Q&A answer
     - Parking information provided

VERIFY: Response order is workflow-then-QA (not QA-then-workflow)
VERIFY: Both parts addressed in single response
VERIFY: NO fallback message
```

### Verify: Workflow Progressed

```
VERIFY: Now at Step 3 (room selection)
VERIFY: Date locked in (07.02.2026)
VERIFY: Room options presented
```

---

## Alternative Test: Room Selection + Q&A

```
ACTION: Send hybrid with room selection + question:
---
Room A please. What's included in the standard package?
---

WAIT: Response appears
```

### Verify: Both Handled

```
VERIFY: Room A selected (workflow action)
VERIFY: Package details explained (Q&A)
VERIFY: Flow continues toward offer
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Workflow action processed first
- [ ] Q&A answered second
- [ ] Both in single response
- [ ] Workflow state correctly updated
- [ ] No fallback messages
