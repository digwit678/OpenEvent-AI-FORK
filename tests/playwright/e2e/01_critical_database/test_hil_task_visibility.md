# DB-003: HIL Task Visibility in Manager Panel

**Test ID:** DB-003
**Category:** Database Operations
**Flow:** Any HIL-triggering action -> Verify task in Manager Tasks
**Pass Criteria:** HIL tasks visible and actionable in UI

---

## Test Steps

### Trigger HIL Task via Offer

```
ACTION: Navigate, reset client
ACTION: Complete full flow to offer:
  - Send booking (25 people, 08.06.2026)
  - Confirm date
  - Select Room B
  - Get offer
WAIT: Offer generated
```

### Accept Offer

```
ACTION: Accept: "I accept this offer"
WAIT: Response (may trigger HIL for final approval)
```

### Check Manager Tasks Panel

```
VERIFY: In UI, locate "📋 Manager Tasks" section
VERIFY: Task visible with:
  - [ ] Client email visible
  - [ ] Event details shown
  - [ ] Draft message visible (if applicable)
  - [ ] "Approve" button present
  - [ ] "Reject" button present
```

### Verify in Database

```bash
python3 -c "
import json
with open('backend/events_database.json') as f:
    db = json.load(f)
for e in db.get('events', []):
    if 'test-db003' in str(e).lower():
        hil = e.get('pending_hil_requests', [])
        print(f'HIL tasks: {len(hil)}')
        for h in hil:
            print(f'  - Type: {h.get(\"type\")}')
            print(f'  - Status: {h.get(\"status\")}')
"
```

### Verify: Task Data

```
VERIFY in database:
  - [ ] pending_hil_requests array populated
  - [ ] Task has type (e.g., "offer_approval")
  - [ ] Task has status (e.g., "pending")
  - [ ] Task has created_at timestamp
  - [ ] Draft message included (if applicable)
```

---

### Test HIL Action

```
ACTION: Click "Approve" on the HIL task
WAIT: Task processed
```

### Verify: Task Completed

```
VERIFY: Task removed from Manager Tasks panel OR marked complete
VERIFY: Workflow continues (client notified)
VERIFY: Database updated:
  - pending_hil_requests cleared or marked done
  - audit_log shows approval
```

---

## Pass Criteria

- [ ] HIL task created in database
- [ ] Task visible in UI panel
- [ ] Task details correct
- [ ] Approve/Reject buttons work
- [ ] Task completion updates database
- [ ] Workflow continues after approval
