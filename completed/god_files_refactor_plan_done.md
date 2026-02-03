# Plan: God-File Refactor (Steps 1-5, Change Propagation, Verbalizer, LLM Adapter, Orchestrator, Entrypoint)

Date: 2026-01-21
Source review: docs/reports/ARCHITECTURE_REVIEW_AND_PLAN_2026_01_19.md
Guardrails: docs/architecture/MASTER_ARCHITECTURE_SHEET.md

## Goal
Reduce god-file complexity by splitting responsibilities into focused modules while keeping behavior stable. The end state is smaller step handlers with thin orchestration, isolated logic units, and safe public APIs.

## Scope
- workflows/steps/step1_intake/trigger/step1_handler.py
- workflows/steps/step2_date_confirmation/trigger/step2_handler.py
- workflows/steps/step3_room_availability/trigger/step3_handler.py
- workflows/steps/step4_offer/trigger/step4_handler.py
- workflows/steps/step5_negotiation/trigger/step5_handler.py
- workflows/change_propagation.py
- ux/universal_verbalizer.py
- workflows/llm/adapter.py
- workflow_email.py
- main.py

## Non-goals
- No feature changes, new behaviors, or policy changes.
- No package layout normalization or DB schema changes (handled elsewhere).
- No LLM provider migration; only internal structure changes.

## Guardrails (Do Not Break)
- Step 1 always runs before pre-route; preserve pipeline order.
- Confirm-anytime is idempotent; do not detour on duplicate confirmations.
- Change-anytime requires anchoring; avoid unbound date/room updates.
- Capture-anytime: billing/contact info must persist even if OOC.
- Verbalizer hard facts must remain exact (dates, prices, units).
- Prefer unified_detection over regex fallbacks.

## Refactor Pattern (Repeat per File)
1. Baseline: record LOC/top-level def count; run a fast regression subset.
2. Extract pure helpers first (no DB writes, no state mutation).
3. Extract rendering/formatting next (message assembly only).
4. Move state mutations into small, named functions with clear inputs.
5. Keep stepX_handler.process as a thin orchestrator.
6. Use local imports to avoid circular dependencies; add a third helper module if needed.
7. Update re-export shims if public imports exist (process.py already re-exports in steps).

## Suggested PR Order (One File per PR)
1. Step 4 Offer (smaller surface, sets pattern).
2. Step 5 Negotiation (classification already extracted).
3. Step 3 Room Availability (largest ROI, more involved).
4. Step 2 Date Confirmation (already partially extracted).
5. Step 1 Intake (highest risk due to early pipeline).
6. Change Propagation (routing-sensitive).
7. Universal Verbalizer (LLM safety logic).
8. LLM Adapter (provider plumbing).
9. workflow_email.py (remove CLI/debug helpers).
10. main.py (split app entrypoint if still needed).

## Extraction Map (From Review)
| File | New Modules (Targets) | Notes |
| --- | --- | --- |
| step1_handler.py | event_bootstrap.py, intent_routing.py, entity_merge.py, detours.py, qna_bridge.py | Build on existing extracted helpers (normalization, detection, entity_extraction). |
| step2_handler.py | date_resolution.py, confirmation_flow.py, message_formatting.py, qna_bridge.py | Reuse existing modules where possible (confirmation.py, step2_utils.py, step2_menu.py). |
| step3_handler.py | availability_evaluation.py, conflict_resolution.py, product_sourcing.py, detours.py, messaging.py, qna_bridge.py | Expand current evaluation/selection modules. |
| step4_handler.py | preconditions.py, pricing.py, offer_compose.py, hil_flow.py | compose.py may absorb offer_compose responsibilities. |
| step5_handler.py | classification.py (exists), billing_capture.py, negotiation_responses.py | Keep classification module as source of truth. |
| change_propagation.py | change_detection.py, change_normalization.py, change_routing.py, change_disambiguation.py | Keep change_propagation.py as orchestrator entry. |
| universal_verbalizer.py | prompt_builder.py, facts_verifier.py, fallback_templates.py, llm_gateway.py | llm_gateway can reuse workflows/llm adapter if feasible. |
| workflows/llm/adapter.py | payload.py, provider.py, heuristics.py, sanitizers.py | Keep adapter.py as facade for public imports. |
| workflow_email.py | move CLI/dev helpers to scripts or debug module | Keep runtime orchestration only. |
| main.py | app.py + main_dev.py | Remove import-time side effects from prod entry. |

## File-by-File Checklists

### Step 4 Offer (workflows/steps/step4_offer/trigger/step4_handler.py)
- Extract preconditions (can we build an offer, missing prerequisites).
- Extract pricing assembly and totals into pricing.py (pure helpers where possible).
- Move message/offer payload composition into offer_compose.py or compose.py.
- Keep process() as orchestration; make state mutations explicit (one place).
- Add characterization tests: offer preconditions, pricing totals, HIL draft content.

### Step 5 Negotiation (workflows/steps/step5_negotiation/trigger/step5_handler.py)
- Keep classification.py as authoritative intent detection.
- Extract billing capture and persistence into billing_capture.py.
- Extract response assembly and HIL task setup into negotiation_responses.py.
- Ensure accept/reject/clarify exits stay idempotent and ordered.
- Tests: accept path, reject path, billing capture only, hybrid confirm plus question.

### Step 3 Room Availability (workflows/steps/step3_room_availability/trigger/step3_handler.py)
- Split evaluation into availability_evaluation.py (capacity, ranking, alternatives).
- Move conflict/option resolution into conflict_resolution.py.
- Move missing product handling into product_sourcing.py.
- Move change requests into detours.py (date/requirements/room changes).
- Move response rendering into messaging.py; keep data-only returns from evaluation.
- Preserve existing hashes and room selection semantics.
- Tests: available room path, option path, conflict path, product missing, QnA injection.

### Step 2 Date Confirmation (workflows/steps/step2_date_confirmation/trigger/step2_handler.py)
- Promote large nested flows into confirmation_flow.py.
- Move message formatting and prompt assembly into message_formatting.py.
- Keep date parsing/normalization in existing date_parsing.py and candidate_dates.py.
- Keep QnA bridge in general_qna.py or dedicated qna_bridge.py.
- Tests: candidate suggestions, confirm date, multiple dates, QnA+confirm.

### Step 1 Intake (workflows/steps/step1_intake/trigger/step1_handler.py)
- Separate event_bootstrap (create event/client, initialize state).
- Extract intent_routing (classification decisions + entry guards).
- Extract entity_merge (LLM extraction + profile updates).
- Extract detours (change propagation / route_change_on_updated_variable).
- Extract qna_bridge (hybrid QnA integration).
- Keep process() ordering unchanged; preserve pre-route inputs.
- Tests: event creation, change detection, room/product detection, QnA + confirm.

### Change Propagation (workflows/change_propagation.py)
- Extract detection logic into change_detection.py (detect_change_type, enhanced).
- Move normalization (date/room parsing) into change_normalization.py.
- Move routing decisions into change_routing.py.
- Move clarification prompts into change_disambiguation.py.
- Keep change_propagation.py as orchestrator and compatibility surface.
- Tests: date change vs payment date, room change, requirements change, ambiguous change.

### Universal Verbalizer (ux/universal_verbalizer.py)
- Extract prompt assembly into prompt_builder.py.
- Move hard-facts verification into facts_verifier.py.
- Move fallback content/templates into fallback_templates.py.
- Isolate LLM calls behind llm_gateway.py (or reuse workflows/llm adapter).
- Tests: hard-facts preservation, fallback usage, QnA prompt assembly.

### LLM Adapter (workflows/llm/adapter.py)
- Separate payload shaping and cache keys into payload.py.
- Move provider registry and retry logic into provider.py.
- Move heuristic overrides into heuristics.py.
- Move sanitizers/parsers into sanitizers.py.
- Keep adapter.py as public facade.
- Tests: provider selection, cache hit, sanitized extraction.

### Orchestrator and Entrypoint
- workflow_email.py: remove CLI helpers and debug-only utilities; keep orchestration only.
- main.py: move side effects to main_dev.py or scripts; create app.py for prod-safe FastAPI app.
- Tests: import app without side effects, routing still works, HIL tasks still enqueue.

## Tests and Verification (Minimum)
- Run the smallest high-signal workflow tests from tests/TEST_MATRIX_detection_and_flow.md.
- Add characterization tests for each step before moving logic.
- Verify no changes to pipeline order or detour sequencing.
- Ensure no new direct DB writes from extracted helpers.

## Definition of Done (Per PR)
- The target file shrinks materially; responsibilities are isolated.
- Public imports remain stable or are re-exported.
- Characterization tests pass and no new behavior regressions are observed.
- No new cyclic dependencies or import-time side effects.
