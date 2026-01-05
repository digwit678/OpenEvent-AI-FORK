# Manual UX Conversation Test

This scripted walkthrough exercises the full Workflow v3 path (Steps 1–7) and
prints per-turn state so you can visually confirm HIL gating, detours, and
draft handling.

## Run the script

```bash
cd <repo-root>
python scripts/manual_ux_conversation_test.py
```

The script writes a temporary JSON database (`manual_ux_conversation.json`) and
prints each turn as structured JSON:

```json
{
  "turn": 5,
  "msg_id": "TURN4",
  "action": "offer_draft_prepared",
  "draft_topic": "offer_draft",
  "state": {
    "step": 5,
    "caller": null,
    "thread": "Awaiting Client Response",
    "chosen_date": "10.06.2025",
    "locked_room": "Room A",
    "requirements_hash": "...",
    "room_eval_hash": "...",
    "counter_count": 0
  },
  "offers": [
    {"id": "…-OFFER-1", "status": "Draft"}
  ],
  "audit_tail": {
    "ts": "2025-10-22T20:45:01Z",
    "actor": "system",
    "from_step": 4,
    "to_step": 5,
    "reason": "return_to_caller"
  }
}
```

## Conversation outline

1. **TURN1** – Client asks for dates (Step 1 → Step 2).
2. **TURN2** – Confirms June 10 (Step 2 → Step 3).
3. **TURN3** – System shares availability (awaits HIL).
4. **TURN4** – HIL approves room (Step 3 → Step 4).
5. **TURN5** – Offer generation (Step 4).
6. **TURN6** – Client counters price (Step 5 counter loop).
7. **TURN7** – Client accepts offer (Step 5 accept → Step 6).
8. **TURN8** – Client ups participant count, triggering detour (Step 7 → Step 3).
9. **TURN9**/**TURN10** – Room re-checked and HIL approved, returning to Step 5.
10. **TURN11** – Client confirms and notes deposit payment (Step 7).
11. **TURN12** – HIL sends final confirmation (calendar block, status Confirmed).

Use this printed output to verify:

- Draft responses stay pending until HIL approval.
- `caller_step` jumps to the detour source and is cleared on return.
- Audit entries capture transitions and `return_to_caller`.
- Thread state flips to `Awaiting Client Response` whenever we wait on the client.
