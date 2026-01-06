# EXIT-002: Gibberish Recovery

**Test ID:** EXIT-002
**Category:** Exit/Recovery
**Flow:** Workflow -> Nonsense -> Proper message -> Workflow continues
**Pass Criteria:** Workflow resumes after nonsense without getting stuck

---

## Test Steps

### Setup: Get to Mid-Workflow

```
ACTION: Navigate, reset client
ACTION: Send booking:
---
Subject: Workshop Booking

Workshop for 20 people, February 2026.

test-exit002@example.com
---

WAIT: Response with date options
ACTION: Confirm: "14.02.2026"
WAIT: Room options appear
```

### Send Multiple Nonsense Messages

```
ACTION: Send gibberish:
---
asdfasdf
---

WAIT: Clarification request

ACTION: Send more gibberish:
---
qwerty 123 ???
---

WAIT: Another clarification

ACTION: Send off-topic:
---
I like pizza
---

WAIT: Redirect
```

### Verify: Not Stuck

```
VERIFY: System still responsive
VERIFY: Not in error state
VERIFY: Not repeating same message infinitely
VERIFY: Booking context still exists
```

### Resume Proper Workflow

```
ACTION: Send valid room selection:
---
Sorry about that. Let's go with Room A.
---

WAIT: Response appears
```

### Verify: Complete Recovery

```
VERIFY: Room A selected
VERIFY: Flow continues toward offer
VERIFY: No reference to previous nonsense
VERIFY: NO fallback message
```

### Complete to Offer

```
ACTION: Get offer
WAIT: Offer appears

VERIFY: Offer correct (Room A, 14.02.2026)
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Multiple nonsense messages don't crash system
- [ ] System remains responsive
- [ ] Proper message resumes workflow
- [ ] No "stuck" loops
- [ ] Full flow completion possible
- [ ] No fallback messages
