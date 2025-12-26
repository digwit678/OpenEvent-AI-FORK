# DEP-002: Deposit as Fixed Amount

**Test ID:** DEP-002
**Category:** Deposit
**Flow:** 4 -> Accept -> Fixed deposit amount shown
**Pass Criteria:** Fixed deposit displayed correctly per policy

---

## Test Steps

### Complete Flow to Offer Acceptance

```
ACTION: Navigate, reset client
ACTION: Send small booking:
---
Subject: Small Workshop

Workshop for 10 people on 26.04.2026.
Half-day, basic room only.

test-dep002@example.com
---

WAIT: Response
ACTION: Complete date and room selection
WAIT: Offer appears
```

### Note Offer Total

```
VERIFY: Record total (e.g., CHF 800 for small event)
```

### Accept Offer

```
ACTION: Accept: "I accept"
WAIT: Response
ACTION: Provide billing
WAIT: Deposit information
```

### Verify: Fixed Deposit Amount

```
# If policy uses minimum deposit amount:
VERIFY: Deposit shown as fixed amount (e.g., CHF 500 minimum)
VERIFY: Fixed amount NOT percentage-based
  - e.g., 30% of CHF 800 = CHF 240
  - But minimum is CHF 500
  - Display shows CHF 500

# If policy uses flat deposit:
VERIFY: Deposit matches policy flat rate
VERIFY: Same regardless of total
```

### Alternative: Large Event with Cap

```
# If policy caps maximum deposit:
ACTION: Navigate, reset client
ACTION: Book very large event (CHF 20,000 total)
ACTION: Complete to deposit stage

VERIFY: Deposit capped at maximum (e.g., CHF 5,000)
VERIFY: NOT 30% of CHF 20,000 = CHF 6,000
```

---

## Policy Variations to Test

```
Common deposit policies:
1. Flat rate: Always CHF X
2. Percentage with minimum: 30% OR minimum CHF 500
3. Percentage with maximum: 30% OR maximum CHF 5,000
4. Tiered: <CHF 2,000 = 50%, >CHF 2,000 = 30%

Test whichever policy is configured
```

---

## Pass Criteria

- [ ] Fixed/minimum deposit enforced
- [ ] Amount matches policy
- [ ] Not incorrectly calculated as percentage
- [ ] Maximum caps respected (if applicable)
- [ ] Payment flow works
