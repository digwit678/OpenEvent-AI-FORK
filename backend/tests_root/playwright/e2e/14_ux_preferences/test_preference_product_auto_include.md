# PREF-003: Product Auto-Include from Preferences

**Test ID:** PREF-003
**Category:** Preferences
**Flow:** 1 -> 2 -> 3 -> 4 (verify products auto-included in offer)
**Pass Criteria:** Mentioned products/services automatically included in offer

---

## Test Steps

### Send Request with Product Preferences

```
ACTION: Navigate, reset client
ACTION: Send email mentioning specific products/services:
---
Subject: Corporate Meeting - April 2026

Planning a half-day meeting for 15 executives.

We'll need:
- Morning coffee and pastries
- Projector and presentation equipment
- Flipchart and markers
- Lunch buffet for the group

Date: 05.04.2026
Please suggest appropriate rooms.

test-pref003@example.com
---

WAIT: Response appears
```

### Complete Date and Room Selection

```
ACTION: Confirm date: "05.04.2026 confirmed"
WAIT: Room options

ACTION: Select room: "Room B sounds good"
WAIT: Response moves toward offer
```

### Verify: Products Auto-Included in Offer

```
WAIT: Offer presented (or HIL task appears)

IF HIL task appears:
  ACTION: Approve it

VERIFY: Offer includes mentioned products:
  - [ ] Coffee service / morning refreshments
  - [ ] Projector / presentation equipment
  - [ ] Flipchart
  - [ ] Lunch / catering
VERIFY: Products listed as line items
VERIFY: Prices shown for each product
VERIFY: Total reflects all included items
VERIFY: NO fallback message
```

### Verify: No Redundant Product Questions

```
VERIFY: System did NOT ask "Do you need catering?"
VERIFY: System did NOT ask "Would you like equipment?"
VERIFY: Products auto-captured from initial message
```

---

## Additional Test: Partial Product Mention

```
ACTION: Navigate, reset client
ACTION: Send email with casual product reference:
---
Subject: Team Offsite

Quick booking for 20 people on 12.04.2026.
We just need a room with coffee available.

test-pref003b@example.com
---

WAIT: Complete flow to offer
VERIFY: Coffee mentioned in offer
VERIFY: Other products NOT assumed (no lunch, no equipment unless requested)
```

---

## Pass Criteria

- [ ] Products captured from initial message
- [ ] Offer includes all mentioned products
- [ ] Prices calculated correctly
- [ ] No redundant product questions asked
- [ ] Casual mentions also captured
- [ ] Only mentioned products included (no assumptions)
