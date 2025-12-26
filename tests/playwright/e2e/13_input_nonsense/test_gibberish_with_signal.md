# NONS-003: Gibberish with Embedded Valid Signal

**Test ID:** NONS-003
**Category:** Nonsense Detection
**Flow:** Mixed message -> Extract valid signal -> Continue workflow
**Pass Criteria:** Valid information extracted despite surrounding nonsense

---

## Test Steps

### Setup: Start Booking

```
ACTION: Navigate, reset client
ACTION: Send initial request:
---
Subject: Meeting Room

Need a meeting room for 20 people, February 2026.

test-nons003@example.com
---

WAIT: Response with date options
```

### Send Gibberish with Valid Date

```
ACTION: Send mixed message:
---
lol ok ya sure haha 14.02.2026 sounds good lmao
---

WAIT: Response appears
```

### Verify: Date Extracted Despite Noise

```
VERIFY: Date (14.02.2026) captured successfully
VERIFY: Response confirms the date
VERIFY: Flow continues to room selection
VERIFY: "lol", "haha", "lmao" NOT treated as intent
VERIFY: Message NOT rejected as pure gibberish
VERIFY: NO fallback message
```

---

### Test: Gibberish with Room Name

```
ACTION: When room options shown, send:
---
uhhhh idk maybe Room A?? whatever works tbh
---

WAIT: Response appears
```

### Verify: Room Extracted

```
VERIFY: Room A selected successfully
VERIFY: Uncertainty markers ("idk", "maybe", "whatever") not blocking
VERIFY: Flow continues toward offer
VERIFY: NO fallback message
```

---

### Test: Informal Acceptance

```
ACTION: When offer shown, send:
---
ya sure i accept this lol 👍
---

WAIT: Response appears
```

### Verify: Acceptance Processed

```
VERIFY: Offer acceptance processed
VERIFY: "ya sure" interpreted as affirmative
VERIFY: Emoji not causing confusion
VERIFY: Flow continues (billing/deposit)
VERIFY: NO fallback message
```

---

### Test: Edge Case - Date in Gibberish Stream

```
ACTION: Navigate, reset client
ACTION: Complete new intake, then send:
---
soooo like yeah i was thinking maybe hmm 21.02.2026 could work but idk we'll see lol
---

WAIT: Response appears
```

### Verify: Signal Extraction

```
VERIFY: Date extracted (21.02.2026)
VERIFY: Uncertainty ("idk", "we'll see") may trigger confirmation
VERIFY: But system doesn't reject message entirely
VERIFY: NO fallback message
```

---

## Pass Criteria

- [ ] Valid dates extracted from noisy text
- [ ] Valid room names extracted from casual speech
- [ ] Acceptance detected despite informal language
- [ ] Filler words/slang don't block processing
- [ ] Emojis don't cause confusion
- [ ] Flow continues with extracted data
- [ ] No fallback messages
