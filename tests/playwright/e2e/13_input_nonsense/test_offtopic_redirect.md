# NONS-002: Off-Topic Message Redirect

**Test ID:** NONS-002
**Category:** Nonsense Detection
**Flow:** Off-topic -> Polite redirect -> Workflow continues
**Pass Criteria:** Off-topic messages get polite redirect, not fallback

---

## Test Steps

### Setup: Start Booking

```
ACTION: Navigate, reset client
ACTION: Send initial request:
---
Subject: Event Inquiry

Planning a corporate dinner for 25 people in April 2026.

test-nons002@example.com
---

WAIT: Response with date options
```

### Send Off-Topic Message

```
ACTION: Send completely unrelated message:
---
I really love Star Wars! Have you seen the latest movie?
---

WAIT: Response appears
```

### Verify: Polite Redirect

```
VERIFY: Response politely redirects to booking
VERIFY: Response does NOT:
  - Engage in Star Wars discussion
  - Get confused about intent
  - Fall back to generic error
VERIFY: Response DOES:
  - Acknowledge message briefly (optional)
  - Redirect to booking context
  - Remind of pending date confirmation
VERIFY: NO fallback message
```

### Continue with Booking

```
ACTION: Return to booking:
---
Ha, sorry about that. Let's go with 05.04.2026.
---

WAIT: Response appears
```

### Verify: Flow Continues

```
VERIFY: Date confirmed
VERIFY: Room options presented
VERIFY: NO confusion from previous off-topic
VERIFY: NO fallback message
```

---

## Alternative: Multiple Off-Topic Messages

```
ACTION: Send another off-topic after redirect:
---
What's your favorite food?
---

WAIT: Response appears
```

### Verify: Consistent Handling

```
VERIFY: Same polite redirect behavior
VERIFY: Still maintains booking context
VERIFY: NO escalation to fallback
VERIFY: NO getting "stuck" in loop
```

---

## Pass Criteria

- [ ] Off-topic detected
- [ ] Polite redirect provided
- [ ] Booking context maintained
- [ ] Easy return to workflow
- [ ] Multiple off-topics handled gracefully
- [ ] No fallback messages
