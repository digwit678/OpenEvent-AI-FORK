# LLM-003: Prices Match Database

**Test ID:** LLM-003
**Category:** LLM Accuracy
**Flow:** Offer generation
**Pass Criteria:** All prices in offer match database values exactly

---

## Test Steps

### Get Offer with Known Pricing

```
ACTION: Navigate, reset client
ACTION: Send specific booking:
---
Subject: Team Meeting

Meeting for 25 people on 07.04.2026.
Room A, full day.
Need projector and coffee service.

test-llm003@example.com
---

WAIT: Response
ACTION: Complete date/room confirmation
WAIT: Offer generated
```

### Verify: Room Price Correct

```
VERIFY: Room rental price matches database:
  - Room A full-day rate
  - Check rooms_database.json or equivalent
  - Exact CHF amount

EXAMPLE:
  - Database: Room A = CHF 1,500/day
  - Offer shows: CHF 1,500
  - ✓ Match
```

### Verify: Product Prices Correct

```
VERIFY: Each product price matches database:
  - [ ] Projector: CHF [database value]
  - [ ] Coffee service: CHF [database value]

VERIFY: NO made-up prices
VERIFY: NO "estimated" prices when exact available
```

### Verify: Calculations Correct

```
VERIFY: Subtotals add up correctly:
  - Room: CHF 1,500
  - Projector: CHF 150
  - Coffee: CHF 200
  - Subtotal: CHF 1,850 ✓

VERIFY: Tax/fees calculated correctly (if applicable)
VERIFY: Total is arithmetic sum of line items
```

---

### Cross-Check with Database

```
ACTION: After test, verify prices:

1. Read rooms pricing from database
2. Read products pricing from database
3. Compare each line item
4. Confirm totals match

python3 -c "
import json
with open('backend/events_database.json') as f:
    db = json.load(f)
# Check room and product prices
"
```

---

### Edge Case: Large Event Pricing

```
ACTION: Book large event (100 people)
VERIFY: Per-person costs scale correctly
VERIFY: No flat rate applied incorrectly
VERIFY: Volume discounts applied if policy exists
```

---

## Pass Criteria

- [ ] Room prices match database
- [ ] Product prices match database
- [ ] Calculations correct
- [ ] No invented prices
- [ ] Totals add up exactly
- [ ] Large events priced correctly
