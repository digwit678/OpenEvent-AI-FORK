# DB-001: Event Creation in Database

**Test ID:** DB-001
**Category:** Database Operations
**Flow:** 1 (intake) -> Verify event created in database
**Pass Criteria:** Event record created with correct initial data

---

## Test Steps

### Send Initial Request

```
ACTION: Navigate, reset client
ACTION: Send booking:
---
Subject: Database Test Event

Planning an event for 35 people in May 2026.
Full-day workshop.

test-db001@example.com
---

WAIT: Response appears
```

### Verify: Event Created

```bash
# Check database file
python3 -c "
import json
with open('backend/events_database.json') as f:
    db = json.load(f)
for e in db.get('events', []):
    if 'test-db001@example.com' in str(e):
        print(f'Event ID: {e.get(\"event_id\")}')
        print(f'Step: {e.get(\"current_step\")}')
        print(f'Participants: {e.get(\"requirements\", {}).get(\"participants\")}')
        print(f'Email: {e.get(\"client_email\")}')
"
```

### Verify: Initial Data Correct

```
VERIFY in database:
  - [ ] event_id exists (UUID format)
  - [ ] client_email = "test-db001@example.com"
  - [ ] current_step = 1 or 2
  - [ ] requirements.participants = 35
  - [ ] created_at timestamp present
```

---

### Continue and Verify Updates

```
ACTION: Confirm date: "15.05.2026"
WAIT: Room options
```

### Verify: Database Updated

```bash
python3 -c "
import json
with open('backend/events_database.json') as f:
    db = json.load(f)
for e in db.get('events', []):
    if 'test-db001@example.com' in str(e):
        print(f'Step: {e.get(\"current_step\")}')
        print(f'Date: {e.get(\"chosen_date\")}')
        print(f'Date confirmed: {e.get(\"date_confirmed\")}')
"
```

### Verify: Date Persisted

```
VERIFY in database:
  - [ ] chosen_date = "2026-05-15" (ISO format)
  - [ ] date_confirmed = True
  - [ ] current_step = 2 or 3
```

---

## Pass Criteria

- [ ] Event record created on first message
- [ ] Correct event_id assigned
- [ ] Client email captured
- [ ] Participants captured
- [ ] Updates persist on each step
- [ ] Date persisted correctly
