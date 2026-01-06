# PERS-001: Billing Persistence from Step 1

**Test ID:** PERS-001
**Category:** Persistence
**Flow:** 1 (with billing) -> 2 -> 3 -> 4 (billing NOT re-asked)
**Pass Criteria:** Billing provided early is remembered at offer stage

---

## Test Steps

### Provide Billing in Initial Request

```
ACTION: Navigate, reset client
ACTION: Send booking with billing details:
---
Subject: Corporate Event Booking

Planning a strategy meeting for 25 executives on 14.03.2026.
Half-day with lunch.

Billing information:
Company: Acme Corp
Address: 123 Business Street
City: 8000 Zurich
Contact: John Smith

test-pers001@example.com
---

WAIT: Response appears
```

### Complete Flow to Offer

```
ACTION: Confirm date when offered: "14.03.2026 confirmed"
WAIT: Room options

ACTION: Select room: "Room A please"
WAIT: Offer or offer preparation

ACTION: Get offer if not automatic
WAIT: Offer appears
```

### Verify: Billing NOT Re-Asked

```
VERIFY: Offer generated without billing prompt
VERIFY: Billing details preserved from Step 1:
  - Company: Acme Corp
  - Address: 123 Business Street
  - City: 8000 Zurich
VERIFY: Response does NOT ask "Please provide billing details"
VERIFY: NO fallback message
```

### Accept Offer

```
ACTION: Accept: "I accept this offer"
WAIT: Response
```

### Verify: Billing Used in Acceptance

```
VERIFY: Billing already attached to confirmation
VERIFY: No billing collection step triggered
VERIFY: Flow continues to deposit/confirmation
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Billing captured at Step 1
- [ ] Billing persisted through Steps 2-3
- [ ] Billing auto-populated at Step 4
- [ ] No duplicate billing request
- [ ] Offer acceptance uses saved billing
