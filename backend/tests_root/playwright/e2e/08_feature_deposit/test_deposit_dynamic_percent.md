# DEP-001: Deposit as Dynamic Percentage

**Test ID:** DEP-001
**Category:** Deposit
**Flow:** 4 -> Accept -> Deposit calculated as percentage
**Pass Criteria:** Deposit amount calculated as correct percentage of total

---

## Test Steps

### Complete Flow to Offer Acceptance

```
ACTION: Navigate, reset client
ACTION: Send booking:
---
Subject: Large Conference

Conference for 60 people on 19.04.2026.
Full day with catering.

test-dep001@example.com
---

WAIT: Response
ACTION: Complete date confirmation and room selection
WAIT: Offer appears
```

### Note Offer Total

```
VERIFY: Record total offer amount (e.g., CHF 3,500)
```

### Accept Offer

```
ACTION: Accept: "I accept this offer"
WAIT: Response
ACTION: Provide billing if requested
WAIT: Deposit information
```

### Verify: Deposit as Percentage

```
VERIFY: Deposit amount shown
VERIFY: Deposit is correct percentage of total:
  - If 30% deposit: CHF 3,500 * 0.30 = CHF 1,050
  - Amount matches expected percentage
VERIFY: Percentage is stated OR
VERIFY: Math checks out against total
VERIFY: "Pay Deposit" button or payment instruction visible
VERIFY: NO fallback message
```

### Process Deposit

```
ACTION: Click "Pay Deposit" (if available)
WAIT: Confirmation

VERIFY: Deposit marked as paid
VERIFY: Flow continues toward final confirmation/site visit
VERIFY: NO fallback message
```

---

## Calculation Verification

```
Given:
- Room rental: CHF 2,000
- Catering: CHF 1,200
- Equipment: CHF 300
- Total: CHF 3,500
- Deposit rate: 30%

Expected deposit: CHF 1,050

VERIFY: Displayed deposit matches calculation
```

---

## Pass Criteria

- [ ] Deposit amount displayed
- [ ] Amount is correct percentage
- [ ] Percentage matches policy (e.g., 30%)
- [ ] Payment mechanism works
- [ ] Flow continues after deposit
