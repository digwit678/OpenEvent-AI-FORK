# HIL-001: Manager Request by Keyword

**Test ID:** HIL-001
**Category:** Special HIL Request
**Flow:** Any step -> "speak to manager" -> HIL task created
**Pass Criteria:** Manager keyword triggers HIL routing

---

## Test Steps

### Test at Step 1 (Intake)

```
ACTION: Navigate, reset client
ACTION: Send request with manager keyword:
---
Subject: Need to Speak with Management

I need to speak to the manager about a special arrangement for our event.
50 people, sometime in March.

test-hil001@example.com
---

WAIT: Response appears
```

### Verify: HIL Task Created

```
VERIFY: Response acknowledges manager request
VERIFY: Response indicates human will follow up:
  - "I'll connect you with our manager" OR
  - "A team member will reach out" OR
  - "Someone from our team will contact you"
VERIFY: Check Manager Tasks panel in UI
VERIFY: HIL task appears with:
  - Client message visible
  - "Manager request" or similar label
  - Approve/action buttons available
VERIFY: NO fallback message
```

---

### Test at Step 2 (Date Confirmation)

```
ACTION: Navigate, reset client
ACTION: Start normal booking (30 people, April)
WAIT: Date options
ACTION: Request manager:
---
Before I confirm the date, I really need to speak to the manager about pricing.
---

WAIT: Response appears
```

### Verify: HIL Created from Step 2

```
VERIFY: Manager request acknowledged
VERIFY: HIL task created
VERIFY: Booking context preserved
VERIFY: NO fallback message
```

---

### Test at Step 4 (Offer)

```
ACTION: Navigate, reset client
ACTION: Complete flow to offer stage
ACTION: Request manager at offer:
---
This looks good but I want to discuss the terms with your manager.
---

WAIT: Response appears
```

### Verify: HIL Created from Step 4

```
VERIFY: HIL task created
VERIFY: Offer state preserved
VERIFY: Client notified about manager follow-up
VERIFY: NO fallback message
```

---

## Keyword Variations

```
Test these keywords work:
- "speak to manager"
- "talk to manager"
- "need a manager"
- "contact your manager"
- "speak with management"
- "I want to talk to a person"
- "human assistance"
```

---

## Pass Criteria

- [ ] "Manager" keyword detected
- [ ] HIL task created in Manager Tasks
- [ ] Works at Steps 1, 2, 3, 4
- [ ] Booking context preserved
- [ ] Polite acknowledgment sent
- [ ] No fallback messages
