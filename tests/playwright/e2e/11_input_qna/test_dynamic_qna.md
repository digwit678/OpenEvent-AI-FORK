# QNA-002: Dynamic Q&A (Date-Dependent Information)

**Test ID:** QNA-002
**Category:** Q&A
**Flow:** Q&A subpath with database lookup
**Pass Criteria:** Dynamic questions answered with current availability data

---

## Test Steps

### Test Case A: Room Availability on Specific Date

```
ACTION: Navigate, reset client
ACTION: Send availability question:
---
Subject: Availability Check

Which rooms are available on 14.02.2026?

test-qna002a@example.com
---

WAIT: Response appears
```

### Verify: Dynamic Availability

```
VERIFY: Response lists available rooms for 14.02.2026
VERIFY: Rooms listed are actually available (matches database)
VERIFY: Unavailable rooms NOT listed, OR marked as unavailable
VERIFY: NO fallback message
VERIFY: This is Q&A only - no booking started
```

---

### Test Case B: Capacity for Date

```
ACTION: Send follow-up:
---
What's the largest group you can accommodate on March 7th, 2026?
---

WAIT: Response appears
```

### Verify: Capacity Answer

```
VERIFY: Response mentions maximum capacity
VERIFY: Capacity based on available rooms for that date
VERIFY: If Room A (largest) unavailable, shows next best
VERIFY: NO fallback message
```

---

### Test Case C: Price Range Question

```
ACTION: Send question:
---
What's the price range for a full-day booking for 30 people?
---

WAIT: Response appears
```

### Verify: Pricing Answer

```
VERIFY: Response provides price range or example
VERIFY: Prices are realistic (match database ranges)
VERIFY: May mention "depends on room selection"
VERIFY: NO fallback message
```

---

### Test Case D: Next Available Date

```
ACTION: Send question:
---
When is Room A next available?
---

WAIT: Response appears
```

### Verify: Next Availability

```
VERIFY: Response provides specific date(s)
VERIFY: Dates are actually available (matches calendar)
VERIFY: Dates are in the future
VERIFY: NO fallback message
```

---

### Transition to Booking (Verify Q&A Doesn't Block Workflow)

```
ACTION: Now start actual booking:
---
Great, I'd like to book Room A for 25 people on one of those dates.
---

WAIT: Response appears
```

### Verify: Workflow Starts

```
VERIFY: System transitions from Q&A to workflow
VERIFY: Booking process begins
VERIFY: Previous Q&A context may be used
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Room availability answered dynamically
- [ ] Capacity information accurate for date
- [ ] Pricing information provided
- [ ] Next available date queried successfully
- [ ] All dynamic answers match database state
- [ ] Q&A doesn't block subsequent booking
- [ ] No fallback messages
