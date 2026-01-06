# DB-002: Room Lock Persistence

**Test ID:** DB-002
**Category:** Database Operations
**Flow:** 3 (room selection) -> Verify locked_room_id persists
**Pass Criteria:** Room selection creates lock that persists

---

## Test Steps

### Complete to Room Selection

```
ACTION: Navigate, reset client
ACTION: Send booking:
---
Subject: Room Lock Test

Event for 30 people on 22.05.2026.

test-db002@example.com
---

WAIT: Response
ACTION: Confirm date: "22.05.2026"
WAIT: Room options
```

### Select Room

```
ACTION: Select room: "Room A please"
WAIT: Response confirms room
```

### Verify: Room Locked in Database

```bash
python3 -c "
import json
with open('backend/events_database.json') as f:
    db = json.load(f)
for e in db.get('events', []):
    if 'test-db002@example.com' in str(e):
        print(f'Locked Room ID: {e.get(\"locked_room_id\")}')
        print(f'Room Eval Hash: {e.get(\"room_eval_hash\")}')
        print(f'Step: {e.get(\"current_step\")}')
"
```

### Verify: Lock Data

```
VERIFY in database:
  - [ ] locked_room_id = "room_a" (or Room A identifier)
  - [ ] room_eval_hash present (SHA256 hash)
  - [ ] current_step >= 3
```

---

### Verify: Lock Survives Date Change

```
ACTION: Change date: "Actually, let's do 29.05.2026 instead"
WAIT: Response
```

### Check if Room Still Available

```bash
# Check if room lock preserved or invalidated correctly
python3 -c "
import json
with open('backend/events_database.json') as f:
    db = json.load(f)
for e in db.get('events', []):
    if 'test-db002@example.com' in str(e):
        print(f'Date: {e.get(\"chosen_date\")}')
        print(f'Locked Room: {e.get(\"locked_room_id\")}')
        # Room should be checked for new date
"
```

### Verify: Appropriate Behavior

```
VERIFY: Either:
  - Room A still available on new date: lock preserved
  - Room A unavailable: lock cleared, new selection required
VERIFY: Hash updated if room re-evaluated
```

---

## Pass Criteria

- [ ] Room lock created on selection
- [ ] locked_room_id persisted
- [ ] room_eval_hash generated
- [ ] Lock persists across messages
- [ ] Date change triggers appropriate re-evaluation
