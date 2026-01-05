# Common Playwright MCP Test Patterns

## Navigation & Setup

### Fresh Start Pattern
```
1. Navigate to http://localhost:3000
2. If "Reset Client" button enabled:
   - Click "Reset Client"
   - Accept confirmation dialog ("Reset data for...?")
   - Accept result dialog ("Client reset complete...")
3. Verify: "Paste a client email below to start"
```

### Send Message Pattern
```
1. Find textarea (message input)
2. Type message content
3. Click Send button (or press Enter)
4. Wait for "Shami is typing..." to appear then disappear
5. Wait for new assistant message
6. Capture response text
```

---

## Verification Patterns

### No Fallback Check
After EVERY response, verify:
```
ASSERT response NOT contains: "[FALLBACK:"
ASSERT response NOT contains: "I'll follow up shortly"
ASSERT response NOT contains: "workflow processing failed"
ASSERT response NOT contains: "empty_workflow_reply"
```

### Database Check
```python
import json
with open('backend/events_database.json') as f:
    db = json.load(f)
# Find event by email
for e in db.get('events', []):
    if 'YOUR_EMAIL' in json.dumps(e):
        print(e)
```

### HIL Task Check
```
1. Look for "Manager Tasks - Client Approvals" section
2. If present, verify:
   - Task card visible
   - Draft message shown
   - Approve/Reject buttons enabled
```

---

## Common Email Templates

### Basic Inquiry (30 people, February)
```
Subject: Event Inquiry - February 2026

We're planning an event for 30 people in February 2026.
Looking for a suitable room with projector and coffee service.

Best regards,
Test User
test@example.com
```

### With Specific Date
```
Subject: Workshop - 14.02.2026

Planning a workshop for 25 people on 14.02.2026.
Need: projector, U-shape seating, morning coffee.

Thanks,
test@example.com
```

### With Preferences
```
Subject: Private Dinner - March 2026

Planning a dinner for 15 guests in March 2026.
Looking for elegant private dining, wine pairing, multi-course menu.

test@example.com
```

---

## Step Identification

| Step | Indicators in Response |
|------|------------------------|
| 1 (Intake) | "date", "when", "capacity" questions |
| 2 (Date) | Date options shown, calendar references |
| 3 (Room) | Room names (A/B/C/D/E), capacity, features |
| 4 (Offer) | Prices, CHF, total, deposit, products |
| 5 (Negotiation) | Accept/decline, billing, counter |
| 7 (Confirmation) | Site visit, final approval, deposit paid |

---

## HIL Approval Pattern

```
1. Locate "Manager Tasks" section (right side panel)
2. Find task card matching current step
3. Optional: Add manager notes in textarea
4. Click "Approve & Send" (green button)
5. Wait for task to disappear
6. Verify new message appears in chat
```

---

## Deposit Payment Pattern

```
1. Locate "Deposit Required: CHF X.XX" section
2. Click "Pay Deposit" button
3. Accept alert dialog ("Deposit of CHF X.XX marked as paid")
4. Verify deposit section shows "Paid" or disappears
5. HIL task should now be approvable
```

---

## Error Recovery

### If Fallback Detected
1. Note the exact fallback message
2. Check browser console for errors
3. Check backend logs: `tail -f tmp-debug/live/*.log`
4. Test fails - document the failure

### If Workflow Stuck
1. Send clarifying message
2. If still stuck, reset client and restart
3. Document at which step it stuck

---

## Timestamp Pattern for Unique Emails

Use timestamp to ensure fresh client:
```
email: test-{YYYYMMDD}-{HHMMSS}@example.com
Example: test-20251224-143522@example.com
```
