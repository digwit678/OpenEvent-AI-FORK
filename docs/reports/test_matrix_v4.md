# Test Matrix V4

## Intake
- missing_email/date/capacity → loops; no duplicate prompts
- shortcut_capacity_ok → Step 3 skips capacity prompt
- shortcut_wish_products → ranking later, not gating

## Date
- next5 none/one/many feasible (≥ TODAY, Europe/Zurich; blackouts/buffers)
- detour_from_room_change_date → confirm then return

## Room
- available / option_only / unavailable
- requirements_change → hash mismatch triggers re-eval
- unchanged_hash → no re-eval

## Products/Offer
- ≤5 rank by wish; >5 asks narrowing
- special request approved/denied loop
- compose→HIL approve→send → Awaiting Client

## Gatekeeping & UX
- P1..P4 enforced; HIL gate on sends (except tight mini-loop)
- footer presence: Step / Next / State

## Determinism
- fixed seed room order
- DST boundary around Europe/Zurich TODAY cutoff

## Detours
- caller_step set; dependent steps only
- date change after offer: skip Step 3 if still valid, else re-run Step 3
