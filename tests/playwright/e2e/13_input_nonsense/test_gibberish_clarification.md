# NONS-001: Gibberish Detection with Clarification

**Test ID:** NONS-001
**Category:** Nonsense Detection
**Flow:** Nonsense -> Clarification request -> Workflow continues
**Pass Criteria:** Gibberish triggers clarification, not API call or fallback

---

## Test Steps

### Setup: Start Booking

```
ACTION: Navigate, reset client
ACTION: Send initial request:
---
Subject: Room Booking

Looking for a room for 30 people in March 2026.

test-nons001@example.com
---

WAIT: Response with date options
```

### Send Pure Gibberish

```
ACTION: Send nonsense message:
---
asdfghjkl qwerty zxcvbn
---

WAIT: Response appears
```

### Verify: Clarification Requested

```
VERIFY: Response is polite clarification request
VERIFY: Response does NOT:
  - Make assumptions about intent
  - Process as date confirmation
  - Process as Q&A
  - Trigger heavy LLM processing
VERIFY: Response DOES:
  - Ask for clarification
  - Maintain context of booking
  - Remain professional
VERIFY: NO fallback message
VERIFY: NO "I'll follow up shortly" or similar
```

### Recover with Valid Message

```
ACTION: Send valid response:
---
Sorry, typo. Let's go with 14.03.2026.
---

WAIT: Response appears
```

### Verify: Workflow Resumes

```
VERIFY: Date confirmed (14.03.2026)
VERIFY: Flow continues to room selection
VERIFY: Previous gibberish forgotten/ignored
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Gibberish detected as nonsense
- [ ] Polite clarification requested
- [ ] No assumptions made
- [ ] Workflow state preserved
- [ ] Recovery with valid message works
- [ ] No fallback messages
