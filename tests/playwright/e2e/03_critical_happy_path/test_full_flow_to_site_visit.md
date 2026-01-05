# E2E-001: Full Flow to Site Visit

**Test ID:** E2E-001
**Category:** Happy Path
**Steps:** 1 -> 2 -> 3 -> 4 -> 5 -> 7
**Pass Criteria:** Site visit message reached, no fallback messages

---

## Prerequisites

- Backend running: `./scripts/dev/dev_server.sh`
- Frontend running: `cd atelier-ai-frontend && npm run dev`
- Fresh client (use Reset Client or unique email)

---

## Test Steps

### Step 1: Navigate and Reset

```
ACTION: Navigate to http://localhost:3000
ACTION: Click "Reset Client" if visible (accept confirmation dialogs)
VERIFY: Page shows "Paste a client email below to start"
```

### Step 2: Send Initial Email (Intake)

```
ACTION: Type in textarea:
---
Subject: Team Workshop Request - February 2026

Dear Team,

We are planning a team strategy workshop for 30 people in February 2026.
We'd prefer a Saturday if possible, ideally February 7th or 14th.

Requirements:
- Projector and screen
- Coffee breaks (morning and afternoon)
- U-shape seating arrangement

Looking forward to your availability.

Best regards,
Test User
test-e2e-001@example.com
+41 79 123 45 67
---

ACTION: Click Send
WAIT: Until "Shami is typing..." disappears
VERIFY: Response contains date options or room availability
VERIFY: Response does NOT contain "[FALLBACK:"
```

### Step 3: Confirm Date (Step 2)

```
ACTION: Type: "07.02.2026 works perfectly for us"
ACTION: Click Send
WAIT: Response appears
VERIFY: Date acknowledged (07.02.2026)
VERIFY: Room options presented
VERIFY: NO fallback message
```

### Step 4: Select Room (Step 3)

```
ACTION: Type: "Room B looks good. Please proceed with that."
ACTION: Click Send
WAIT: Response appears
VERIFY: Room B confirmed
VERIFY: Offer or HIL task appears
VERIFY: NO fallback message
```

### Step 5: Handle HIL if Present

```
IF Manager Tasks section visible:
  ACTION: Click "Approve & Send" button
  WAIT: Task disappears, new message appears
VERIFY: Offer details visible (date, room, products, total)
```

### Step 6: Accept Offer (Step 4/5)

```
ACTION: Type: "Yes, I accept the offer."
ACTION: Click Send
WAIT: Response appears
VERIFY: Acceptance acknowledged
VERIFY: Billing address requested OR deposit shown
VERIFY: NO fallback message
```

### Step 7: Provide Billing Address

```
ACTION: Type: "Billing address: Test Company AG, Bahnhofstrasse 10, 8001 Zurich, Switzerland"
ACTION: Click Send
WAIT: Response appears
VERIFY: Billing captured
VERIFY: Deposit payment requested OR HIL task appears
```

### Step 8: Pay Deposit

```
IF "Pay Deposit" button visible:
  ACTION: Click "Pay Deposit" button
  ACTION: Accept confirmation dialog
  VERIFY: Deposit marked as paid
```

### Step 9: Approve Final HIL

```
IF Manager Tasks section visible with offer_message task:
  VERIFY: Task shows "Deposit: CHF X.XX Paid"
  ACTION: Click "Approve & Send"
  WAIT: New message appears
```

### Step 10: Verify Site Visit Stage

```
VERIFY: Response contains ONE of:
  - "site visit"
  - "Let's continue with site visit bookings"
  - "preferred dates or times" (for site visit)
VERIFY: NO fallback message in entire conversation
```

---

## Database Verification

```bash
# Check events_database.json
python3 -c "
import json
with open('backend/events_database.json') as f:
    db = json.load(f)
for e in db.get('events', []):
    if 'test-e2e-001@example.com' in json.dumps(e):
        print(f'Step: {e.get(\"current_step\")}')
        print(f'Date: {e.get(\"chosen_date\")}')
        print(f'Room: {e.get(\"locked_room_id\")}')
        print(f'Billing: {e.get(\"billing_details\", {}).get(\"street\")}')
        print(f'Deposit: {e.get(\"deposit_paid\")}')
"
```

**Expected:**
- `current_step`: 5 or 7
- `chosen_date`: 2026-02-07
- `locked_room_id`: room_b (or similar)
- `billing_details.street`: Bahnhofstrasse 10
- `deposit_paid`: True

---

## Pass Criteria Checklist

- [ ] All 10 steps completed without error
- [ ] No `[FALLBACK:` messages in any response
- [ ] Site visit stage reached
- [ ] Database shows correct event state
- [ ] HIL tasks appeared and were actionable

---

## Failure Indicators

- Response contains `[FALLBACK:`
- Response contains `I'll follow up shortly`
- Workflow stops before site visit
- Database shows wrong step or missing data
- HIL task never appears for offer
