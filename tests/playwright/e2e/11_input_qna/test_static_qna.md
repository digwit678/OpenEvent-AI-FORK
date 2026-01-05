# QNA-001: Static Q&A (Factual Information)

**Test ID:** QNA-001
**Category:** Q&A
**Flow:** Q&A subpath (no workflow progression)
**Pass Criteria:** Static factual questions answered accurately

---

## Test Steps

### Test Case A: Opening Hours

```
ACTION: Navigate, reset client
ACTION: Send question about opening hours:
---
Subject: Quick Question

What are your opening hours?

test-qna001a@example.com
---

WAIT: Response appears
```

### Verify: Static Answer

```
VERIFY: Response contains opening hours information
VERIFY: Information is specific (days, times)
VERIFY: Information matches venue facts
VERIFY: NO fallback message
VERIFY: NO workflow step triggered
```

---

### Test Case B: Parking Information

```
ACTION: Send follow-up question:
---
Do you have parking available? How many spaces?
---

WAIT: Response appears
```

### Verify: Parking Answer

```
VERIFY: Response addresses parking:
  - Availability (yes/no)
  - Number of spaces (if available)
  - Location or access instructions
VERIFY: NO fallback message
```

---

### Test Case C: Location/Address

```
ACTION: Send question:
---
What's your exact address? Is there public transport nearby?
---

WAIT: Response appears
```

### Verify: Location Answer

```
VERIFY: Response includes:
  - Full address
  - Public transport options (if applicable)
VERIFY: NO fallback message
```

---

### Test Case D: Accessibility

```
ACTION: Send question:
---
Is the venue wheelchair accessible?
---

WAIT: Response appears
```

### Verify: Accessibility Answer

```
VERIFY: Response addresses accessibility
VERIFY: Specific details provided
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Opening hours answered correctly
- [ ] Parking information provided
- [ ] Address and transport answered
- [ ] Accessibility information given
- [ ] All answers are factual (from venue database)
- [ ] No fallback messages
- [ ] Q&A doesn't trigger workflow steps
