# V4 DAG & Change Propagation (Authoritative)

## 1) Canonical Variables (state init)
- `chosen_date` (and `date_confirmed`)
- `requirements = { participants, seating_layout, duration(start–end), special_requirements }`
- `requirements_hash` (hash of requirements)
- `locked_room_id` (null until user picks/accepts)
- `room_eval_hash` (snapshot of requirements_hash used for last room check)
- `selected_products` (catering/add-ons)
- `offer_hash` (snapshot of accepted commercial terms)
- `caller_step` (who asked for the detour)

## 2) Dependency DAG (logical only)
participants ┐
seating_layout ┼──► requirements ──► requirements_hash
duration ┘
special_requirements ┘
        │
        ▼
chosen_date ───────────────────────────► Room Evaluation ──► locked_room_id
        │                                    │
        │                                    └────────► room_eval_hash
        ▼
Offer Composition ──► selected_products ──► offer_hash
        ▼
Confirmation / Deposit

**Reading the DAG:** Room evaluation depends on the confirmed date and the current requirements. The offer depends on the room decision (and unchanged room_eval_hash) plus products. Confirmation depends on the accepted offer (or reservation/deposit rules). This mirrors the “detour and return” principle and hash guards to avoid redundant re-checks.

## 3) Minimal Re-Run Matrix (what actually needs to re-execute)

| Client change | Re-run exactly… | Skip… | Guard that decides |
|---|---|---|---|
| **Date** | Step 2 (Date Confirmation). If new date confirmed and a room search is still required, Step 3; otherwise return to the original caller. | Products, offer, negotiation — unless the room outcome must change. | `date_confirmed` is re-set; Step 2 owns date; downstream steps consume it. |
| **Room (different/bigger/etc.)** | Step 3 (Room Availability) only; then return to the caller (often Step 4). | Step 2; products. | Step-3 entry guard B (“client asks to change room”). `room_eval_hash` refreshed. |
| **Requirements (participants/layout/duration/special)** | Step 3 re-evaluates room fit; then back to caller. | Step 2. | Step-3 entry guard C + `requirements_hash ≠ room_eval_hash` triggers re-check. |
| **Products/Catering** | Stay inside Step 4 (products mini-flow → offer rebuild); no date/room recheck. | Steps 2–3. | Products live in Step 4; no structural dependency upward. |
| **Commercial terms only** (negotiate price/scope without structural changes) | Step 5 (Negotiation) only; accept → Step 7; else end or loop. | Steps 2–3–4 (unless negotiation implies structural change). | Negotiation routing and acceptance handoff. |
| **Deposit/Reservation** | Within Step 7 (option/deposit branches). | Steps 2–4. | Confirmation layer owns payment/option lifecycle. |

The table above is the textual version of “Change-Propagation Logic / Steps Re-evaluated” + the Step-3 entry guards and the global detour/return rules.

## 4) Deterministic Detour Rules (how the jump/return works)
- Always set `caller_step` before jumping.
- Jump to the **owner step** of the changed variable: Date → Step 2, Room/Requirements → Step 3, Products/Offer consistency → Step 4.
- On completion, **return to `caller_step`**, unless the step’s entry guard or hash check proves nothing changed (**fast-skip**).
- **Hashes prevent churn:** If `requirements_hash` is unchanged, skip room re-evaluation. If `offer_hash` still matches, skip transition repairs.

**ASCII detour sketch**
[ c a l l e r ] ──(change detected)──► [ owner step ]
▲ │
└──────────(resolved + hashes)─────────┘

## 5) Fast-Path Rules (to save time)
- **No room recheck** when the client only tweaks products: `requirements_hash == room_eval_hash` → go straight to offer rebuild.
- **Skip Step 3** after a date change **if the same room remains valid** and was explicitly locked for the new date in Step 2’s outcome path. Otherwise, Step 3 runs.
- **Do not re-run Intake**; it never re-executes after creation (HIL edits only).

## 6) “What depends on what?” Cheat-Sheet
- **Step 2 – Date Confirmation** depends on intake record only. Re-runs when client proposes/changes date; any later date change routes here.
- **Step 3 – Room Availability** depends on `date_confirmed`, `requirements → requirements_hash`. Re-runs on Step-3 entry A/B/C; or `requirements_hash ≠ room_eval_hash`. Persists `locked_room_id`, updates `room_eval_hash`.
- **Step 4 – Offer** depends on `date_confirmed`, `locked_room_id`, `room_eval_hash == requirements_hash`, `selected_products`. Any structural invalidation (date/room/requirements) forces detour to 2/3; otherwise only the products loop + recomposition.
- **Step 5 – Negotiation** depends on an existing offer. Purely commercial loop unless a structural change is requested mid-negotiation.
- **Step 7 – Confirmation** depends on accepted offer / option policy. Handles site-visit, reservation, deposit, final confirmation; triggers detours back to 2/3/4 if client changes structure here.

## 7) Three Crisp Change Scenarios (end-to-end)
A) Client ups attendees **24→36** (same date) → Step-3 entry guard C → re-evaluate rooms → (if room still fits) return to caller (often Step 4) **without** touching date/products.  
B) Client changes date **after we sent an offer**. `caller_step=Step 4` → detour to Step 2 → confirm new date → if same room still valid, **skip Step 3** and return to Step 4 to refresh the offer dates; else run Step 3, then back to Step 4.  
C) Client accepts, but asks to **add Prosecco**. Stay in Step 4 products sub-flow → recompute totals → resend offer or proceed directly if already accepted/within policy → Step 7 for final confirmation/deposit. **No** date/room rechecks.
