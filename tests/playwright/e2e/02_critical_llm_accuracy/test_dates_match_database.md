# LLM-002: Dates Match Database/Calendar

**Test ID:** LLM-002
**Category:** LLM Accuracy
**Flow:** Date suggestions and confirmations
**Pass Criteria:** All dates are actually available, not past, not blackout

---

## Test Steps

### Request Date Options

```
ACTION: Navigate, reset client
ACTION: Send booking:
---
Subject: Future Event

Need a room for 25 people sometime in March 2026.

test-llm002@example.com
---

WAIT: Date options presented
```

### Verify: Dates Valid

```
VERIFY: All suggested dates are:
  - [ ] In the future (>= today)
  - [ ] Actually available in calendar
  - [ ] Not on blackout dates
  - [ ] Valid calendar dates (no Feb 30, etc.)

VERIFY: Dates are realistic:
  - Within requested month (March 2026)
  - Business days (unless venue open weekends)

VERIFY: NO past dates suggested
VERIFY: NO fallback message
```

### Request Specific Date Verification

```
ACTION: Ask about specific date:
---
Is 14.03.2026 available?
---

WAIT: Response
```

### Verify: Database Match

```
VERIFY: Response matches actual calendar:
  - If available: confirm it's bookable
  - If unavailable: explain why (booked, blackout, etc.)
VERIFY: NO lying about availability
VERIFY: NO fallback message
```

---

### Edge Case: Request Past Date

```
ACTION: Navigate, reset client
ACTION: Request past date:
---
Subject: Booking

I need a room for 20 people on 01.01.2020.

test-llm002b@example.com
---

WAIT: Response
```

### Verify: Past Date Rejected

```
VERIFY: System doesn't accept past date
VERIFY: Response requests valid future date
VERIFY: NO pretending event is booked for 2020
VERIFY: NO fallback message
```

---

## Calendar Cross-Check

```
For each suggested date:
1. Check calendar_data files
2. Verify room availability
3. Confirm no conflicts
```

---

## Pass Criteria

- [ ] Only future dates suggested
- [ ] Dates match calendar availability
- [ ] Blackout dates respected
- [ ] Past dates rejected
- [ ] Valid calendar dates only (no Feb 30)
