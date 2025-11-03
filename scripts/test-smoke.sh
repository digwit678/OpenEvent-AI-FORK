#!/usr/bin/env bash
set -euo pipefail
pytest -q \
  tests/specs/intake/test_intake_loops.py \
  tests/specs/intake/test_entity_capture_shortcuts.py \
  tests/specs/date/test_date_confirmation_next5.py \
  tests/specs/room/test_room_availability.py \
  tests/specs/room/test_room_detours_hash_guards.py \
  tests/specs/products_offer/test_products_paths_lte5_gt5.py \
  tests/specs/products_offer/test_offer_compose_send.py \
  tests/specs/gatekeeping/test_prereq_P1_P4.py \
  tests/specs/gatekeeping/test_hil_gates.py \
  tests/specs/detours/test_detours_rerun_dependent_only.py \
  tests/specs/detours/test_no_redundant_asks_with_shortcuts.py \
  tests/specs/ux/test_message_hygiene_and_continuations.py \
  tests/e2e_v4/test_full_flow_stubbed.py
