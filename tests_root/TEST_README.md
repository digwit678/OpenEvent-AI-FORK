# Tests overview (target structure)

tests/specs/
  intake/
    test_intake_loops.py
    test_entity_capture_shortcuts.py
  date/
    test_date_confirmation_next5.py
    test_date_rules_blackouts_buffers.py
  room/
    test_room_availability.py
    test_room_detours_hash_guards.py
  products_offer/
    test_products_paths_lte5_gt5.py
    test_special_request_hil_loop.py
    test_offer_compose_send.py
  gatekeeping/
    test_prereq_P1_P4.py
    test_hil_gates.py
  determinism/
    test_determinism_and_time.py
  detours/
    test_detours_rerun_dependent_only.py

tests/fixtures/
  intake_loops.json
  date_next5_cases.json
  blackout_buffer_windows.json
  room_search_cases.json
  products_offer_cases.json
  special_request_cases.json

Legacy tests live in: tests/_legacy/

Utilities (drop-in)
tests/utils/seeds.py
import random
def set_seed(n: int = 1337):
    random.seed(n)
tests/utils/timezone.py
from freezegun import freeze_time
TZ = "Europe/Zurich"
tests/utils/assertions.py
def assert_no_duplicate_prompt(messages, prompt_key):
    count = sum(1 for m in messages if prompt_key in m.get("text",""))
    assert count <= 1

def assert_next_step_cue(msg):
    text = msg.get("text","")
    assert any(k in text for k in ["Next:", "Choose", "Please confirm"])

def assert_wait_state(msg, expected):
    assert msg.get("wait_state") == expected  # "Awaiting Client" | "Waiting on HIL"

Fixtures (seed files)
tests/fixtures/intake_loops.json
{
  "shortcut_capacity_ok": {"text": "We expect 60 people.", "capacity": 60},
  "shortcut_capacity_invalid": {"text": "around fiftyish", "capacity": null},
  "shortcut_wish_products": {"text": "We’ll need a projector and Apéro."}
}
tests/fixtures/date_next5_cases.json
{
  "none_feasible": {"today": "2025-11-03", "candidates": [], "feasible": []},
  "one_feasible": {"today": "2025-11-03", "candidates": ["2025-11-12"], "feasible": ["2025-11-12"]},
  "many_feasible": {"today": "2025-11-03", "candidates": ["2025-11-12","2025-11-14","2025-11-19"], "feasible": ["2025-11-12","2025-11-19"]}
}
tests/fixtures/blackout_buffer_windows.json
{
  "blackouts": ["2025-11-10","2025-12-24"],
  "buffers": [{"days_before":2,"days_after":1}]
}
tests/fixtures/room_search_cases.json
{
  "available": {"date": "2025-11-12", "capacity": 60, "rooms": [{"id":"R1","fits":true,"option":false}]},
  "option_only": {"date": "2025-11-12", "capacity": 60, "rooms": [{"id":"R2","fits":true,"option":true}]},
  "unavailable": {"date": "2025-11-12", "capacity": 200, "rooms": []}
}
tests/fixtures/products_offer_cases.json
{
  "lte5_rank_by_wish": {"wish_products":["Projector","Apéro"], "rooms": ["A","B","C","D","E"]},
  "gt5_needs_narrow": {"wish_products":["Projector"], "rooms": ["A","B","C","D","E","F","G"]},
  "missing_items_approved": {"missing":["Barista"], "hil":"approved"},
  "missing_items_denied": {"missing":["Barista"], "hil":"denied"}
}
tests/fixtures/special_request_cases.json
{
  "approve_all": {"items":["Barista","Stage"], "decision":"approved"},
  "deny_partial": {"items":["Barista"], "decision":"denied"}
}

Optional: human-readable matrix
docs/reports/test_matrix_v4.md
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
