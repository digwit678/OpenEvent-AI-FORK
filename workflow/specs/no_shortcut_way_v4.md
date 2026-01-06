# No Shortcut Way — v4 (Source of Truth)

> See also: `v4_dag_and_change_rules.md`, `v4_shortcuts_and_ux.md`, `v4_actions_payloads.md`

## Legend
- **[LLM-Classify]**, **[LLM-Extract (Regex→NER→LLM)]**, **[LLM-Verb]**
- **[COND]** deterministic gate, **[HIL]** approval, **[WAIT]** thread state
- **[CALL→db.func]** via adapters (LLM never touches DB directly)
- **[DB-READ] / [DB-WRITE]**, **[TRIGGER]** send/holds/deposit monitors
- DOTTED arrows = loops with labels “↺ UNTIL …”
- Timezone for “TODAY”: **Europe/Zurich**

## Entities (thread-scoped)
`msg, user_info, client_id, event_id, intent, res, task, chosen_date, date_confirmed, capacity, locked_room_id, requirements{participants, seating_layout, duration(start–end), special_requirements}, requirements_hash, room_eval_hash, wish_products[], selected_products[], caller_step, offer_id, status(Lead|Option|Confirmed|Lost), thread_state(AwaitingClient|WaitingOnHIL|Closed)`

---

## Gatekeeping (must be TRUE to enter next step)
- **→ Step 2 (Date):** `event_id` exists; email known; date **not** confirmed.
- **→ Step 3 (Room):** `date_confirmed=true`, capacity present, requirements present; `requirements_hash` computed.
- **→ Step 4 (Offer compose/send):**  
  P1 `date_confirmed` • P2 `locked_room_id` **and** `requirements_hash==room_eval_hash` • P3 capacity present • P4 products phase completed (or explicitly skipped).  
  First unmet ⇒ detour: P1→Step2, P2/P3→Step3, P4→Products mini-flow.
- All client-facing sends need **HIL** approval except the tight **products mini-loop**.
- **Detours:** set `caller_step`; only dependent steps re-run (hash guards prevent redundant eval).

---

## DB Adapter Surface (engine only; never LLM)
- `db.events.create(intake)` [DB-WRITE] → `event_id`
- `db.events.update_date(event_id, date)` [DB-WRITE]
- `db.events.lock_room(event_id, room_id, room_eval_hash)` [DB-WRITE]
- `db.events.sync_lock(event_id)` [DB-READ/WRITE] (date/room/hashes/products/totals)
- `db.events.set_lost(event_id)` [DB-WRITE]
- `db.events.set_confirmed(event_id)` [DB-WRITE]
- `db.dates.next5(base_or_today, rules)` [DB-READ] (≥ **TODAY(Europe/Zurich)**, blackout/buffer rules)
- `db.rooms.search(date, requirements)` [DB-READ]
- `db.products.rank(rooms, wish_list)` [DB-READ]
- `db.options.create_hold(event_id, expiry)` [DB-WRITE]
- `db.policy.read(event_id)` [DB-READ] (deposit required?)
- `db.offers.create(event_id, payload)` [DB-WRITE] (status=Lead → `offer_id`)

---

## Shortcut Way vs No Shortcut Way

### Definitions
- **No Shortcut Way (default orchestration):** Engine advances strictly by gates:  
  Step 1 (Intake loops) → Step 2 (Date confirm, next-5 ≥ TODAY) → Step 3 (Room availability) → Step 4 (Products/Offer path).  
  Entry to each step is controlled by [COND] gates (P1..P4, hashes). DB access only via adapters.

- **Shortcut Way (entity capture policy):** Engine **eagerly captures and persists any relevant entity out of order** (e.g., capacity mentioned at Intake) and **reuses it later** when the owning step needs it—**without re-asking**—provided validations pass.  
  Shortcuts **never skip gates**; they only **prevent redundant questions** at the owning step.

### Shortcut Capture Rules (deterministic)
1) **Eager Capture:** On any message run Regex → NER → LLM-refine. If an entity for a downstream step is detected (e.g., `participants`), persist it with `source="shortcut"` and `captured_at_step`.
2) **Validation:** Apply the owning step’s validator (capacity: positive int; date: ISO Y-M-D). If invalid/ambiguous, **do not** persist; the owning step will ask later.
3) **No Re-Ask:** At the owning step, if a **valid** shortcut exists and the client hasn’t changed it, **use it silently** (no duplicate prompt).
4) **Change Detection:** If client later supplies a different value, mark prior as superseded, recompute hashes, and detour **only dependent steps**.
5) **Precedence:** Values given at the owning step override shortcuts.
6) **Never Skip Gates:** Shortcut presence does not allow early entry; P1..P4 and entry guards still apply.
7) **UX Guarantee (never left in the dark):** Every client/handoff turn includes:
   - **Current step**, **Next expected action** (client or HIL),
   - **Wait state** (Awaiting Client / Waiting on HIL),
   - a clear continuation cue (choices or simple instruction).

**Examples**
- Capacity stated at Intake → stored as shortcut → Step 3 won’t ask capacity again.
- “Projector” mentioned at Intake → stored in `wish_products` → Step 4 uses for ranking; no extra ask unless `>5 rooms` narrowing is needed.

---

## State Diagram (v4)

```mermaid
stateDiagram-v2
  %% [CALL→db.func] marks adapter calls; dotted arrows show loops (↺ UNTIL ...)

  [*] --> Step1_Intake

  state Step1_Intake {
    [*] --> S1_ClassifyExtract
    S1_ClassifyExtract: [LLM-Classify] intent\n[LLM-Extract(Regex→NER→LLM)] entities
    S1_ClassifyExtract --> S1_CreateEvent
    S1_CreateEvent: [CALL→db.events.create] [DB-WRITE] → event_id
    S1_CreateEvent --> S1_CheckEmail

    S1_CheckEmail: [COND] email present?
    S1_CheckEmail --> S1_AskEmail: no
    S1_AskEmail: [LLM-Verb] ask email → [TRIGGER] send → [WAIT]
    S1_AskEmail -.-> S1_CheckEmail: ↺ UNTIL email known

    S1_CheckEmail --> S1_CheckDate: yes
    S1_CheckDate: [COND] date complete (Y–M–D)?
    S1_CheckDate --> S1_AskDate: no
    S1_AskDate: [LLM-Verb] ask complete date → [TRIGGER] send → [WAIT]
    S1_AskDate -.-> S1_CheckDate: ↺ UNTIL date complete

    S1_CheckDate --> S1_CheckCapacity: yes
    S1_CheckCapacity: [COND] capacity present (int)?
    S1_CheckCapacity --> S1_AskCapacity: no
    S1_AskCapacity: [LLM-Verb] ask capacity → [TRIGGER] send → [WAIT]
    S1_AskCapacity -.-> S1_CheckCapacity: ↺ UNTIL capacity known

    S1_CheckCapacity --> S1_StoreWishes: yes
    S1_StoreWishes: capture wish_products (ranking only; not gating)
    S1_StoreWishes --> [*]
  }
  Step1_Intake --> Step2_Date

  state Step2_Date {
    [*] --> S2_Next5
    S2_Next5: [CALL→db.dates.next5] [DB-READ]\nbase|TODAY(Europe/Zurich), rule ≥TODAY, blackouts/buffers
    S2_Next5 --> S2_Present
    S2_Present: [LLM-Verb] present 5 + invite proposal → [HIL] approve → [TRIGGER] send → [WAIT]
    S2_Present --> S2_ParseReply: on Client reply
    S2_ParseReply: [LLM-Extract(Regex→NER→LLM)] parse → ISO
    S2_ParseReply --> S2_Feasibility

    S2_Feasibility: [COND] feasible dates?
    S2_Feasibility --> S2_LoopNone: none feasible
    S2_LoopNone: [LLM-Verb] explain none; refresh next5 → [HIL] → [TRIGGER] send → [WAIT]
    S2_LoopNone -.-> S2_Present: ↺ UNTIL feasible/confirmed

    S2_Feasibility --> S2_OneFeasible: exactly one feasible
    S2_OneFeasible: [LLM-Verb] confirm {d*} → [TRIGGER] send → [WAIT]
    S2_OneFeasible --> S2_Confirm: on Client "confirm"

    S2_Feasibility --> S2_MultiFeasible: multiple feasible
    S2_MultiFeasible: [LLM-Verb] disambiguate → [TRIGGER] send → [WAIT]
    S2_MultiFeasible --> S2_Confirm: on Client choose

    S2_Confirm: [CALL→db.events.update_date] [DB-WRITE]\nchosen_date=d*; date_confirmed=true
    S2_Confirm --> [*]
  }
  Step2_Date --> Step3_Room

  state Step3_Room {
    [*] --> S3_EntryGuards
    S3_EntryGuards: [COND] Entry A/B/C (no room | room change | req change)\n+ date_confirmed + (requirements_hash vs room_eval_hash)
    S3_EntryGuards --> S3_Eval

    S3_Eval: [CALL→db.rooms.search] [DB-READ]\nargs: chosen_date, requirements
    S3_Eval --> S3_Unavailable: no matching rooms
    S3_Unavailable: [LLM-Verb] unavailability + propose date/capacity change → [HIL] → [TRIGGER] send → [WAIT]
    S3_Unavailable --> Step2_Date: on Client new date (caller_step=3)
    S3_Unavailable -.-> S3_EntryGuards: ↺ on req change

    S3_Eval --> S3_Available: ≥1 room free
    S3_Available: [LLM-Verb] availability → [HIL] → [TRIGGER] send → [WAIT]
    S3_Available --> S3_LockAndForward: on Client "proceed"
    S3_LockAndForward: [CALL→db.events.lock_room] [DB-WRITE]\nlocked_room_id; room_eval_hash=requirements_hash
    S3_LockAndForward --> Step4_Offer

    S3_Eval --> S3_Option: all suitable on option
    S3_Option: [LLM-Verb] explain option → [HIL] → [TRIGGER] send → [WAIT]
    S3_Option --> S3_LockAndForward: on "accept option"
    S3_Option --> Step2_Date: on new date (caller_step=3)
    S3_Option -.-> S3_EntryGuards: ↺ on req change
  }

  %% Products/Offer path (still part of “done for Steps 1–3” check)
  Step3_Room --> Step4_Offer
  state Step4_Offer {
    [*] --> S4_Prereq
    S4_Prereq: [COND] P1 date_confirmed • P2 locked_room_id & hashes ok • P3 capacity present • P4 products done?
    S4_Prereq --> S4_Detour2: if P1 fails
    S4_Detour2 --> Step2_Date: (caller_step=4)
    S4_Prereq --> S4_Detour3: if P2 or P3 fail
    S4_Detour3 --> Step3_Room: (caller_step=4)
    S4_Prereq --> S4_Products: if P4 incomplete

    S4_Products: Products/Catering mini-flow
    S4_Products --> S4_Lte5: if ≤5 rooms
    S4_Products --> S4_Gt5: if >5 rooms

    S4_Lte5: [LLM-Verb] table (confirmed + up to 5 alts)\n(if wish_products → rank by fulfillment; show missing)
    S4_Lte5 --> S4_Special: if client requests missing items
    S4_Lte5 --> S4_Compose: on client row-select / end-intent

    S4_Gt5: [LLM-Verb] ask "specific products/catering?"
    S4_Gt5 --> S4_Compose: if client selects directly
    S4_Gt5 --> S4_ReRank: if client provides wishes

    S4_ReRank: [CALL→db.products.rank] [DB-READ]\nrooms, wish_list → ranked table
    S4_ReRank --> S4_Special: if missing items remain
    S4_ReRank --> S4_Compose: else

    S4_Special: [LLM-Verb] special-request → [HIL] decide → [WAIT] Waiting on HIL
    S4_Special -.-> S4_Special: ↺ UNTIL HIL decision
    S4_Special --> S4_Compose: HIL approved
    S4_Special -.-> S4_Lte5: ↺ HIL denied → recommend alternatives

    S4_Compose: [LLM-Verb] professional offer + totals → [HIL] approve
    S4_Compose --> S4_Send: on HIL approved
    S4_Send: [CALL→db.offers.create] [DB-WRITE] status=Lead → offer_id\n[TRIGGER] send → [WAIT] Awaiting Client
  }
```

---

## Operational Outline (Steps 0–12)
0. **Thread bootstrap:** Intake webhook/HIL handoff provides `msg`, `client_id`, optional seeded entities; thread_state defaults to `AwaitingClient`.
1. **Step 1 classify/extract:** Determine intent, capture entities, create intake record via `db.events.create`.
2. **Step 1 loops:** Ensure email/contact present; prompt again if missing; persist shortcut captures for downstream steps.
3. **Step 2 prep:** When ready, call `db.dates.next5` with TODAY (Europe/Zurich) and blackout/buffer data.
4. **Step 2 presentation:** Verbally present none/one/many-feasible flows; HIL approves outbound messages.
5. **Step 2 confirmation:** Parse client reply; on confirmation, update date/flags, set `caller_step` for detours.
6. **Step 3 entry guards:** Re-check requirements hashes, room change intents, and ensure prerequisites before searching.
7. **Step 3 evaluation:** Query rooms, branch to available/option/unavailable narratives, including detour triggers.
8. **Step 3 decision:** On proceed/option accept, lock room, persist `room_eval_hash`, hand off to Step 4.
9. **Step 3 detours:** On new date/requirements, set `caller_step`, jump to Step 2 or loop within Step 3 per guard rules.
10. **Step 4 prerequisites:** Validate P1..P4 before products flow; detour back if any prerequisite fails.
11. **Step 4 products mini-flow:** Handle ≤5 vs >5 room presentations, special request HIL loops, and wish-based re-ranking.
12. **Step 4 compose/send:** Compose commercial offer, route through HIL approval, send with footer, remain Awaiting Client.

## Control Flow Summary
- Steps advance strictly via gates; each detour records `caller_step` so control returns post-resolution.
- Intake (Step 1) never reruns post-creation; later edits happen via HIL tooling rather than conversational loops.
- Step 2 owns date confirmation; Step 3 owns room/requirements; Step 4 owns products/offer consistency.
- HIL approvals guard all client sends apart from the tight products loop where rapid iteration is required.

## Redundancy & Hash Guards
- `requirements_hash` vs `room_eval_hash` suppress redundant room searches; equality allows skipping Step 3.
- `offer_hash` (tracked in offer spec) ensures confirmation flows do not rebuild unchanged offers.
- Shortcuts reuse captured entities but still validate before gate entry, preventing double prompts.
- Detours test hashes on re-entry; unchanged state results in fast-return to `caller_step`.

## UX Footer Contract
Every outbound message includes the standard footer: `Step: <StepName> · Next: <expected action/options> · State: <Awaiting Client|Waiting on HIL>`. The footer keeps clients and HIL aligned on progress, upcoming actions, and wait states, fulfilling the “never left in the dark” guarantee.
