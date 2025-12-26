# HIL-003: Special HIL Request from Any Step

**Test ID:** HIL-003
**Category:** Special HIL Request
**Flow:** Steps 1,2,3,4 -> Special request -> HIL created
**Pass Criteria:** HIL requests work from every workflow step

---

## Test Steps

### Step 1: HIL at Intake

```
ACTION: Navigate, reset client
ACTION: Send special request at intake:
---
Subject: Complex Request

We have a very unusual event - need to discuss options with your team.
It's a multi-day corporate retreat for 100+ people.
Please have someone call me.

test-hil003-s1@example.com
---

WAIT: Response appears

VERIFY: HIL task created
VERIFY: Response acknowledges human follow-up
VERIFY: NO fallback message
```

---

### Step 2: HIL at Date Confirmation

```
ACTION: Navigate, reset client
ACTION: Start booking: "30 people, March 2026"
WAIT: Date options

ACTION: Request special handling:
---
These dates don't work. Can your event coordinator suggest alternatives?
We have very specific requirements.
---

WAIT: Response appears

VERIFY: HIL task created for coordinator
VERIFY: Booking context preserved
VERIFY: NO fallback message
```

---

### Step 3: HIL at Room Selection

```
ACTION: Navigate, reset client
ACTION: Complete to room selection (30 people, 14.03.2026)
ACTION: Request special handling:
---
None of these rooms are quite right. Can I speak with someone about
customizing the space? We need specific lighting arrangements.
---

WAIT: Response appears

VERIFY: HIL task created
VERIFY: Room selection state preserved
VERIFY: NO fallback message
```

---

### Step 4: HIL at Offer

```
ACTION: Navigate, reset client
ACTION: Complete to offer stage
ACTION: Request negotiation:
---
The pricing seems high for our budget. I need to discuss this with
your sales manager before proceeding.
---

WAIT: Response appears

VERIFY: HIL task created for sales/manager
VERIFY: Offer state preserved
VERIFY: NO fallback message
```

---

### Verify All HIL Tasks in Manager Panel

```
ACTION: Check Manager Tasks section in UI
VERIFY: All 4 HIL tasks visible:
  - Step 1 complex request
  - Step 2 date coordinator
  - Step 3 customization
  - Step 4 pricing negotiation
VERIFY: Each task has:
  - Client message
  - Context info
  - Action buttons
```

---

## Pass Criteria

- [ ] HIL works at Step 1
- [ ] HIL works at Step 2
- [ ] HIL works at Step 3
- [ ] HIL works at Step 4
- [ ] All tasks visible in Manager Tasks
- [ ] Context preserved for each
- [ ] No fallback messages
