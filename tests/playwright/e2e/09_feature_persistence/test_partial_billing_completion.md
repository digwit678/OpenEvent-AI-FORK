# PERS-003: Partial Billing Completion

**Test ID:** PERS-003
**Category:** Persistence
**Flow:** Partial billing -> only missing parts requested
**Pass Criteria:** Only incomplete billing fields requested

---

## Test Steps

### Provide Partial Billing at Intake

```
ACTION: Navigate, reset client
ACTION: Send request with incomplete billing:
---
Subject: Business Meeting

Meeting for 15 people on 21.03.2026.
Bill to: Smith & Co.

test-pers003@example.com
---

WAIT: Response appears
```

### Complete to Offer

```
ACTION: Confirm date and room
ACTION: Get offer
WAIT: Offer appears

ACTION: Accept: "I accept"
WAIT: Response
```

### Verify: Only Missing Fields Requested

```
VERIFY: System asks only for missing billing info:
  - Asks for address (NOT provided)
  - Asks for city (NOT provided)
  - Does NOT ask for company name (already have "Smith & Co.")
VERIFY: Request is specific about what's missing
VERIFY: NO "please provide billing information" generic request
VERIFY: NO fallback message
```

### Complete Missing Fields

```
ACTION: Provide missing info:
---
Address: 456 Commerce Ave, 8001 Zurich
---

WAIT: Response
```

### Verify: Billing Complete

```
VERIFY: Billing now complete with:
  - Company: Smith & Co. (from Step 1)
  - Address: 456 Commerce Ave (just provided)
  - City: 8001 Zurich (just provided)
VERIFY: Flow continues (deposit/confirmation)
VERIFY: NO fallback message
```

---

## Alternative: Provide More Later

```
ACTION: Navigate, reset client
ACTION: Initially provide company only
ACTION: At Step 3, mention: "By the way, our address is 789 Main St"
VERIFY: Address captured and persisted
ACTION: At Step 4 acceptance, only city asked
```

---

## Pass Criteria

- [ ] Partial billing captured
- [ ] Only missing fields requested
- [ ] Previously provided info preserved
- [ ] Mid-flow additions captured
- [ ] Final billing complete
- [ ] No redundant questions
