# HIL-002: Manager Request by Name

**Test ID:** HIL-002
**Category:** Special HIL Request
**Flow:** Any step -> Request specific person -> HIL routed to that person
**Pass Criteria:** Named manager request routes to correct person

---

## Test Setup Note

In production, manager names are dynamically fetched from user login.
For testing, the system should detect common name patterns:
- "Can [Name] help me?"
- "I'd like to speak with [Name]"
- "Please have [Name] contact me"

---

## Test Steps

### Request Specific Person

```
ACTION: Navigate, reset client
ACTION: Send request mentioning a name:
---
Subject: Special Request

I'm planning a wedding reception for 80 guests in June 2026.
Can Sarah help me with this? I spoke with her last time.

test-hil002@example.com
---

WAIT: Response appears
```

### Verify: Named Request Detected

```
VERIFY: Response acknowledges the specific request
VERIFY: Response mentions Sarah (or the named person):
  - "I'll have Sarah contact you" OR
  - "Sarah will follow up with you" OR
  - "I'll pass this to Sarah"
VERIFY: HIL task created with:
  - Routing info indicating "Sarah" OR
  - Tag/label with the name
VERIFY: NO fallback message
```

---

### Alternative: Name Mid-Conversation

```
ACTION: Navigate, reset client
ACTION: Complete normal booking to Step 3
ACTION: Request by name:
---
Actually, could you have Michael look at this booking? He knows our company's requirements.
---

WAIT: Response appears
```

### Verify: Mid-Flow Named Request

```
VERIFY: Request routed to "Michael"
VERIFY: HIL task contains name reference
VERIFY: Booking context preserved
VERIFY: NO fallback message
```

---

### Edge Case: Unknown Name

```
ACTION: Send request with uncommon name:
---
Can Zxywq handle this personally?
---

WAIT: Response appears
```

### Verify: Unknown Name Handling

```
VERIFY: System either:
  - Routes to general manager queue, OR
  - Asks for clarification about the person
VERIFY: Does NOT fail silently
VERIFY: HIL task still created
VERIFY: NO fallback message
```

---

## Name Pattern Detection

```
Test these patterns:
- "Can [Name] help?"
- "I'd like [Name] to call me"
- "Please have [Name] contact me"
- "Is [Name] available?"
- "I worked with [Name] before"
- "[Name] knows our account"
```

---

## Pass Criteria

- [ ] Common names detected in request
- [ ] HIL routed with name info
- [ ] Response mentions the person
- [ ] Unknown names handled gracefully
- [ ] Works mid-conversation
- [ ] No fallback messages
