# V4 Actions / Payload Contracts

## Row selection (email/chat)
Payload
```json
{
  "action": "row_select",
  "row_select_token": "sel_tok_…",
  "event_id": "EVT-…",
  "context": { "step": "Step4_Offer" }
}
```
Server: validate token → apply selection → persist → reply with UX footer.

Confirm date
```json
{
  "action": "confirm_date",
  "date": "YYYY-MM-DD",
  "event_id": "EVT-…",
  "context": { "step": "Step2_Date" }
}
```

Footer (append to all messages)
Step: <StepName> · Next: <expected action/options> · State: <Awaiting Client|Waiting on HIL>

---
