# LLM-001: No Hallucinated Room Names

**Test ID:** LLM-001
**Category:** LLM Accuracy
**Flow:** Any step with room mention
**Pass Criteria:** All room names match database (A, B, C, D, E)

---

## Test Steps

### Request Room Options

```
ACTION: Navigate, reset client
ACTION: Send booking:
---
Subject: Event Inquiry

Looking for a room for 30 people on 14.03.2026.

test-llm001@example.com
---

WAIT: Response
ACTION: Confirm date
WAIT: Room options presented
```

### Verify: Room Names Valid

```
VERIFY: All room names are from database:
  - "Room A" ✓
  - "Room B" ✓
  - "Room C" ✓
  - "Room D" ✓
  - "Room E" ✓

VERIFY: NO invented room names:
  - "The Grand Ballroom" ✗
  - "Executive Suite" ✗
  - "Garden Room" ✗
  - "Conference Hall 1" ✗
  - Any name not in database ✗

VERIFY: NO fallback message
```

### Test: Ask About Non-Existent Room

```
ACTION: Ask about made-up room:
---
What about the Diamond Suite?
---

WAIT: Response
```

### Verify: No Hallucination

```
VERIFY: Response does NOT pretend Diamond Suite exists
VERIFY: Response either:
  - States room doesn't exist, OR
  - Lists available rooms (A, B, C, D, E), OR
  - Asks for clarification
VERIFY: NO fallback message
```

---

## Database Room Verification

```
Cross-check with actual database:
1. Load backend/events_database.json
2. Check rooms list
3. Verify all LLM mentions match exactly

Expected rooms: Room A, Room B, Room C, Room D, Room E
```

---

## Pass Criteria

- [ ] Only database rooms mentioned
- [ ] No invented room names
- [ ] Invalid room requests handled gracefully
- [ ] Room features match database
- [ ] No hallucinated amenities
