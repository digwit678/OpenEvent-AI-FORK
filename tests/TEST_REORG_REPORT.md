# Test Suite Reorganization Report

## Cleanup (2025-11-03)
- Files moved → tests/_legacy/:
  - backend/tests/__init__.py
  - backend/tests/conftest.py
  - backend/tests/workflows/__init__.py
  - backend/tests/workflows/test_availability_and_offer_flow.py
  - backend/tests/workflows/test_event_confirmation_flow.py
  - backend/tests/workflows/test_event_confirmation_post_offer.py
  - backend/tests/workflows/test_event_confirmation_post_offer_actions.py
  - backend/tests/workflows/test_workflow_prompt_behaviour.py
  - backend/tests/workflows/test_workflow_v3_alignment.py
  - backend/tests/workflows/test_workflow_v3_steps_4_to_7.py
  - scripts/manual_ux_conversation_test.py
- Duplicate configs removed: None
- .gitignore additions: Entries for coverage.xml, junit.xml, .pytest_cache/, htmlcov/ already present

## Cleanup (2025-11-04)
- Files moved → tests/_legacy/:
  - None
- Duplicate configs removed:
  - None
- .gitignore additions:
  - None (entries already covered)

## Cleanup (2025-11-05)
- Files moved → tests/_legacy/:
  - None (branch alignment only)
- Duplicate configs removed:
  - None
- .gitignore additions:
  - None
- Notes:
  - Migrated hygiene commit history onto branch feature/agent-workflow-ui-3-1-11-25.

## Cleanup (2025-11-06)
- Files moved → tests/_legacy/:
  - None (directory scaffolding only)
- Duplicate configs removed:
  - None
- .gitignore additions:
  - None
- Notes:
  - Created tests/specs/{intake,date,room,products_offer,gatekeeping,determinism,detours}, tests/utils, tests/fixtures, and docs/reports scaffolding with .gitkeep files for v4 layout.
