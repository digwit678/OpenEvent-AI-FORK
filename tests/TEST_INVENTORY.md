# Test Suite Inventory

**Generated:** 2025-11-27
**Purpose:** Document all existing Python tests, their coverage, type, and status to guide test suite cleanup and expansion.

---

## Summary

| Location | Test Count | Pass | Fail | Notes |
|----------|------------|------|------|-------|
| `backend/tests/smoke/` | 1 | 1 | 0 | API key smoke test |
| `backend/tests_integration/` | 4 | - | - | Requires live OpenAI (AGENT_MODE=openai) |
| `tests/specs/` | ~90 | ~68 | ~22 | Main v4 spec tests |
| `tests/workflows/` | ~75 | ~67 | ~8 | Workflow step tests |
| `tests/gatekeeping/` | 3 | 3 | 0 | Room selection guards |
| `tests/room/` | 1 | 1 | 0 | Room ranking |
| `tests/flows/` | 10 | 5 | 5 | YAML-based flow specs |
| `tests/e2e_v4/` | 2 | 2 | 0 | Stubbed e2e flows |
| `tests/regression/` | 1 | 1 | 0 | Matrix param loader |
| `tests/ux/` | 1 | - | - | Empty placeholder |
| `tests/e2e/` | 1 | - | - | Empty placeholder |
| `tests/_legacy/` | ~20 | - | - | Legacy v3 tests (xfail) |

---

## Detailed Inventory

### backend/tests/smoke/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_workflow_v3_agent.py` | OpenAI API key validation via `load_openai_api_key()` | smoke | **pass** |

### backend/tests_integration/

These tests require live OpenAI configuration (`AGENT_MODE=openai`, `OPENAI_TEST_MODE=1`).

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_e2e_live_openai.py` | Full e2e flow with live LLM: intake → date → room → offer → acceptance | e2e/integration | requires live env |
| `test_room_lock_policy.py` | Room auto-lock policy (ALLOW_AUTO_ROOM_LOCK flag) | integration | requires live env |
| `test_offer_requires_lock.py` | Offer gating on room lock; Step 4 advancement | integration | requires live env |
| `test_offer_acceptance_flow.py` | Offer acceptance → HIL task enqueue | integration | requires live env |

### tests/specs/

#### tests/specs/intake/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_intake_loops.py` | Step 1 intake loops enforce unique prompts (email, date, capacity) | unit | **pass** |
| `test_entity_capture_shortcuts.py` | Shortcut entity capture (capacity, date stated early) | unit | **pass** |

#### tests/specs/date/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_date_confirmation_next5.py` | Step 2 date confirmation: next5 classifications (none/one/many feasible) | unit | **pass** |
| `test_date_rules_blackouts_buffers.py` | Date rules: blackout periods and buffer constraints | unit | **pass** |
| `test_dates_next5.py` | `db.dates.next5` helper behavior | unit | **pass** |
| `test_vague_date_month_weekday_flow.py` | Vague date handling (month + weekday patterns) | unit | **pass** |
| `test_general_room_qna_flow.py` | General room Q&A path (hybrid queries) | integration | **FAIL** (2 tests) |
| `test_general_room_qna_multiturn.py` | Multi-turn general Q&A scenarios | integration | **FAIL** (5 tests) |

#### tests/specs/room/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_room_availability.py` | Step 3 room search classification (available/option/unavailable) | unit | **pass** |
| `test_room_detours_hash_guards.py` | Room detour triggers, hash guard logic | unit | **pass** |
| `test_room_status_unselected_until_selection.py` | Room status progression | unit | **pass** |
| `test_per_room_dates_alternatives_on_confirmed.py` | Per-room date alternatives on confirmed date | unit | **pass** |
| `test_per_room_dates_vague_range.py` | Per-room dates for vague range queries | unit | **FAIL** (1 test) |

#### tests/specs/products_offer/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_offer_compose_send.py` | Step 4 offer compose with footer, HIL gate | unit | **pass** |
| `test_products_paths_lte5_gt5.py` | Products mini-flow: ≤5 rooms vs >5 rooms paths | unit | **pass** |
| `test_special_request_hil_loop.py` | Special request → HIL loop | unit | **pass** |
| `test_table_ranking_by_menu_prefs.py` | Product table ranking by menu preferences | unit | **pass** |

#### tests/specs/detours/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_detours_rerun_dependent_only.py` | Detour logic: only dependent steps re-run | unit | **pass** |
| `test_no_redundant_asks_with_shortcuts.py` | No redundant prompts when shortcuts exist | unit | **pass** |

#### tests/specs/gatekeeping/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_hil_gates.py` | HIL gate enforcement for client sends | unit | **pass** |
| `test_prereq_P1_P4.py` | Step 4 prerequisites P1-P4 validation | unit | **pass** |
| `test_shortcuts_block_without_gates.py` | Shortcuts don't skip gates | unit | **pass** |
| `test_tool_allowlist_and_schema.py` | Tool allowlist schema validation | unit | **pass** |

#### tests/specs/nlu/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_general_qna_classifier.py` | General room Q&A detection without LLM | unit | **pass** |

#### tests/specs/determinism/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_determinism_and_time.py` | Deterministic time handling (freezegun) | unit | **pass** |
| `test_trace_toggle_off_by_default.py` | Debug trace toggle defaults off | unit | **pass** |

#### tests/specs/providers/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_provider_graceful_not_implemented.py` | Provider graceful NotImplemented handling | unit | **pass** |
| `test_provider_registry_openai_default.py` | OpenAI as default provider | unit | **pass** |

#### tests/specs/dag/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_change_propagation.py` | DAG-based change routing (date/room/requirements/products) | unit | **FAIL** (4 tests) |
| `test_change_scenarios_e2e.py` | Change scenario e2e flows | integration | **FAIL** (5 tests) |
| `test_change_integration_e2e.py` | Change detection integration | integration | **FAIL** (4 tests) |

#### tests/specs/ux/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_adapter_prefers_markdown.py` | Adapter markdown preference | unit | **pass** |
| `test_billing_captured_vs_saved_chip.py` | Billing captured vs saved chip display | unit | **pass** |
| `test_debug_badges_and_trackers.py` | Debug badges and trackers | unit | **pass** |
| `test_debug_gate_progress_and_missing_keys.py` | Debug gate progress display | unit | **pass** |
| `test_debug_granularity_filters.py` | Debug granularity filters | unit | **pass** |
| `test_debug_io_summaries.py` | Debug I/O summaries | unit | **pass** |
| `test_debug_no_retro_row_mutation.py` | Debug no retroactive row mutation | unit | **pass** |
| `test_debug_prompt_column_expander.py` | Debug prompt column expander | unit | **pass** |
| `test_debug_subloops_do_not_advance_gates.py` | Debug subloops don't advance gates | unit | **pass** |
| `test_debug_trace_columns_and_vocab.py` | Debug trace columns and vocabulary | unit | **pass** |
| `test_debug_trace_contract.py` | Debug trace API contract | integration | **pass** |
| `test_debug_wait_state_and_current_step.py` | Debug wait state and current step display | unit | **pass** |
| `test_email_composer_uses_markdown.py` | Email composer markdown output | unit | **pass** |
| `test_offer_status_ladder.py` | Offer status progression (Lead→Option→Confirmed) | unit | **pass** |
| `test_step3_action_hints_compact.py` | Step 3 action hints compact display | unit | **pass** |
| `test_timeline_export.py` | Timeline export functionality | unit | **pass** |
| `test_hybrid_queries_and_room_dates.py` | Hybrid queries (rooms + dates + menus) | integration | **FAIL** (1 test) |
| `test_message_hygiene_and_continuations.py` | Message hygiene and continuation handling | unit | **pass** |

### tests/workflows/

#### tests/workflows/qna/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_context_builder.py` | Q&A context builder | unit | **pass** |
| `test_engine.py` | Structured Q&A engine | unit | **pass** |
| `test_extraction.py` | Q&A extraction pipeline | unit | **pass** |
| `test_verbalizer.py` | Q&A verbalizer fallback formatting | unit | **FAIL** (1 test) |
| `test_general_reply.py` | General room Q&A reply generation | unit | **FAIL** (3 tests) |

#### tests/workflows/intake/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_room_choice_followup.py` | Room choice follow-up routing | unit | **FAIL** (1 test) |
| `test_followup_confirmation.py` | Follow-up confirmation handling | unit | **pass** |
| `test_confirmation_backfill.py` | Confirmation backfill logic | unit | **pass** |
| `test_product_update_followup.py` | Product update follow-up | unit | **pass** |
| `test_acceptance_normalization.py` | Acceptance phrase normalization | unit | **pass** |

#### tests/workflows/date/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_confirmation_window_recovery.py` | Confirmation window recovery (relative dates) | unit | **FAIL** (1 test) |

#### tests/workflows/common/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_relative_date_parsing.py` | Relative date parsing | unit | **pass** |

#### tests/workflows/ (root)

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_change_detection_heuristics.py` | Change detection heuristics and pattern matching | unit | **pass** |
| `test_change_routing_steps4_7.py` | Change routing for Steps 4-7 | unit | **pass** |
| `test_change_integration_e2e.py` | Change integration e2e | integration | **FAIL** (1 test) |
| `test_offer_product_operations.py` | Offer product operations (add/remove/update) | unit | **FAIL** (1 test) |
| `test_offer_menu_pricing.py` | Offer menu pricing calculations | unit | **pass** |
| `test_hil_progression.py` | HIL progression through steps | unit | **pass** |

### tests/gatekeeping/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_room_marked_selected_only_after_action.py` | Room marked selected only after action | unit | **pass** |
| `test_room_selection_advances_to_step4.py` | Room selection advances to Step 4 | unit | **pass** |

### tests/room/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_rank_rooms_by_prefs.py` | Room ranking by preferences | unit | **pass** |

### tests/flows/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_flow_specs.py` | YAML-based flow spec runner | integration | 5 pass, 5 **FAIL** |

**Failing flows:**
- `test_flow_general_qna` - General Q&A flow assertions
- `test_flow_normal` - Normal step progression
- `test_flow_past_date` - Past date handling
- `test_flow_week2_december` - Week 2 December scenario
- `test_flow_february_saturday` - February Saturday availability

### tests/e2e_v4/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_full_flow_stubbed.py` | Full stubbed flow: date → room → offer progression | e2e | **pass** (2 tests) |

### tests/regression/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_matrix_param_loader.py` | Matrix parameter loader | unit | **pass** |

### tests/ux/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_step3_no_catering_in_body_before_room.py` | Empty placeholder (no tests) | - | n/a |

### tests/e2e/

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_live_smoke.py` | Empty placeholder (no tests) | - | n/a |

### tests/_legacy/

All tests marked with `pytest.mark.legacy` and `xfail`. These are v3 workflow tests retained for regression reference.

| File | Feature | Type | Status |
|------|---------|------|--------|
| `test_workflow_v3_alignment.py` | V3 workflow step alignment | legacy | xfail |
| `test_workflow_v3_steps_4_to_7.py` | V3 Steps 4-7 | legacy | xfail |
| `test_negotiation_close.py` | V3 negotiation close | legacy | xfail |
| `test_qna_precedence_composite.py` | Q&A precedence composite | legacy | xfail |
| `test_verbalizer_agent.py` | Verbalizer agent | legacy | xfail |
| `test_chatkit_client_tool.py` | Chatkit client tool | legacy | xfail |
| `test_agents_sdk_allowlist.py` | Agents SDK allowlist | legacy | xfail |
| `test_agent_api.py` | Agent API | legacy | xfail |
| `manual_ux_conversation_test.py` | Manual UX conversation (script) | legacy | n/a |
| `smoke/test_workflow_v3_agent.py` | V3 smoke test | legacy | xfail |
| `workflows/test_availability_and_offer_flow.py` | V3 availability/offer flow | legacy | xfail |
| `workflows/test_event_confirmation_flow.py` | V3 event confirmation | legacy | xfail |
| `workflows/test_event_confirmation_post_offer.py` | V3 post-offer confirmation | legacy | xfail |
| `workflows/test_event_confirmation_post_offer_actions.py` | V3 post-offer actions | legacy | xfail |
| `workflows/test_offer_after_lock_offline.py` | V3 offer after lock | legacy | xfail |
| `workflows/test_room_lock_explicit.py` | V3 explicit room lock | legacy | xfail |
| `workflows/test_workflow_prompt_behaviour.py` | V3 prompt behaviour | legacy | xfail |
| `workflows/test_workflow_v3_alignment.py` | V3 alignment (duplicate) | legacy | xfail |
| `workflows/test_workflow_v3_steps_4_to_7.py` | V3 Steps 4-7 (duplicate) | legacy | xfail |

---

## Coverage Gaps (Identified)

### Missing Happy-Path Tests
1. **Step 5 Negotiation** - No dedicated unit tests for accept/decline/counter flows
2. **Step 6 Transition Checkpoint** - No unit tests for blocker collection
3. **Step 7 Event Confirmation** - Limited unit test coverage

### Missing Edge-Case Tests
1. **Counter threshold escalation** (4+ counters → manual review)
2. **Deposit/site-visit subflows** in Step 7
3. **Calendar conflict detection** for room availability
4. **Cross-step detour recovery** scenarios

### Tests Needing Update
1. `test_change_propagation.py` - Change detection API may have evolved
2. `test_general_room_qna_*.py` - Q&A path expectations outdated
3. `test_flow_specs.py` - YAML fixtures need alignment with v4 behavior

---

## Test Utilities

| File | Purpose |
|------|---------|
| `tests/utils/assertions.py` | Common assertions: `assert_wait_state`, `assert_next_step_cue`, `assert_no_duplicate_prompt` |
| `tests/utils/seeds.py` | `set_seed()` for deterministic random |
| `tests/utils/timezone.py` | `TZ`, `freeze_time()` for deterministic time |
| `tests/stubs/dates_and_rooms.py` | Stubbed date/room data for unit tests |
| `tests/fixtures/` | JSON fixtures for various test scenarios |
| `tests/specs/flows/` | YAML flow specifications |

---

## Running Tests

```bash
# Activate environment first
cd /Users/nico/PycharmProjects/OpenEvent-AI
source scripts/dev/oe_env.sh

# Run all v4 tests (default)
pytest

# Run specific test groups
pytest tests/specs/                    # Spec-driven tests
pytest tests/workflows/                # Workflow tests
pytest tests/gatekeeping/              # Gatekeeping tests
pytest tests/flows/                    # YAML flow tests
pytest tests/e2e_v4/                   # E2E v4 tests

# Run legacy tests (xfail expected)
pytest -m legacy

# Run backend tests
pytest backend/tests/smoke/ -q

# Run live integration tests (requires env setup)
export AGENT_MODE=openai
export OPENAI_TEST_MODE=1
pytest backend/tests_integration/ -m integration
```
