# Architecture Review and Implementation Plan (2026-01-19)

## Scope

This review focuses on maintainability and modularity across the backend workflow engine, entrypoints, and LLM plumbing, plus the frontend/back split. It uses the following sources:

- Code: `main.py`, `workflow_email.py`, `workflows/*`, `workflow/*`, `api/*`, `ux/*`, `atelier-ai-frontend/*`
- Docs: `README.md`, `docs/guides/TEAM_GUIDE.md`, `docs/internal/backend/BACKEND_REFACTORING_PLAN_DEC_2025.md`, `docs/internal/backend/BACKEND_REFACTORING_PLAN_DEC_2025_ADDENDUM.md`
- File metrics: line counts and top-level function counts (see table below)

## Overall Structure and Patterns

- Clear frontend/back split: Next.js UI in `atelier-ai-frontend`, FastAPI backend in `main.py` with route modules in `api/routes`.
- Workflow engine is the core product: a step-based state machine, orchestrated by `workflow_email.py` and runtime routing in `workflows/runtime`.
- Layered backend structure is evident: detection (`detection`), domain models (`domain`), integrations (`adapters`), workflow steps (`workflows/steps`), shared workflow logic (`workflows/common`), persistence (`workflows/io`).
- Human-in-the-loop tasking is a first-class design with dedicated runtime APIs in `workflows/runtime/hil_tasks.py`.
- Compatibility shims exist for steps/groups and dynamic import patterns, which preserve behavior but increase coupling.

## Best Practices Observed

- Deterministic state machine with explicit entry guards and requirement hashing reduces nondeterminism and compute waste.
- Pre-route pipeline and router extraction into `workflows/runtime` provides a cleaner orchestrator boundary.
- Step modules are isolated by workflow stage (1-7) and already have extraction scaffolding in place.
- Hard-facts verification in the universal verbalizer provides a safety net against LLM hallucinations.
- HIL gating is consistently threaded through steps, keeping high-risk actions human approved.

## Architectural Issues (Maintainability and Modularity)

1) Package layout inconsistency
- There is a top-level `workflows` package and also a `workflow` package.
- A `backend/` directory exists but is not the Python package; docs refer to `backend.*` imports, which no longer match reality.
- This creates onboarding friction and makes refactors error-prone.

2) God files and mixed concerns
- Several step handlers exceed 1,300-2,900 lines and combine parsing, routing, rendering, and persistence updates.
- Large functions with internal branching make it hard to reason about changes and to isolate tests.

3) Entry-point side effects
- `main.py` clears bytecode caches and mutates env at import time, mixing dev behavior with production entrypoints.
- Import-time side effects reduce composability and complicate integration tests.

4) Persistence and reference data fragmentation
- JSON-based DB files are used directly and sometimes duplicated across locations.
- Room/product data lives in multiple files with different schemas, which creates drift and duplicate mapping logic.

5) LLM integration fragmentation
- LLM usage is split between provider adapters, step logic, and the universal verbalizer.
- Fallback diagnostics and error paths appear in multiple places and lack a single, consistent interface.

6) Compatibility shims and dynamic imports
- Dynamic imports in smart shortcuts and direct private helper imports increase coupling and make refactors fragile.

## God Files Deep Analysis

### Size and Structure Snapshot

| File | LOC | Top-level defs | Role summary | Key risk |
| --- | --- | --- | --- | --- |
| `workflows/steps/step3_room_availability/trigger/step3_handler.py` | 2924 | 45 | Availability evaluation, room ranking, conflict resolution, product sourcing, Q&A bridge | Too many responsibilities in one step
| `workflows/steps/step2_date_confirmation/trigger/step2_handler.py` | 2043 | 16 | Date parsing, candidate generation, confirmation flow, HIL, Q&A bridge | Large core flow inside few functions
| `workflows/steps/step1_intake/trigger/step1_handler.py` | 1840 | 8 | Intent classification, entity extraction, event bootstrap, detours, Q&A | Monolithic `process` with many branches
| `workflows/steps/step4_offer/trigger/step4_handler.py` | 1605 | 19 | Preconditions, pricing, offer composition, HIL acceptance, Q&A | Tight coupling of pricing + messaging
| `workflows/change_propagation.py` | 1460 | 23 | Change detection + routing + disambiguation | Dense heuristics + routing in one file
| `workflows/steps/step5_negotiation/trigger/step5_handler.py` | 1316 | 17 | Negotiation classification, billing capture, acceptance/decline, HIL | Mixed concerns + multiple exit paths
| `ux/universal_verbalizer.py` | 1313 | 13 | Prompt building, LLM call, fact verification, patching | Core safety logic coupled to LLM calls
| `workflows/llm/adapter.py` | 822 | 23 | LLM adapter, caching, heuristics, sanitization | Mixed provider, caching, and parsing
| `workflow_email.py` | 787 | 15 | Orchestrator facade, routing loop, HIL entrypoints | Still contains non-core utilities
| `main.py` | 575 | 16 | App setup, middleware, startup logic, dev behaviors | Production entrypoint with dev side effects

### Deeper Notes by File

#### Step 3 Room Availability (`workflows/steps/step3_room_availability/trigger/step3_handler.py`)
- Responsibilities: ranking rooms, handling conflicts, selecting alternatives, product sourcing, detours, HIL decisions, and Q&A responses.
- Risk: Core decision-making is interleaved with message rendering and state mutations, which complicates regression testing.
- Suggested split targets:
  - `availability_evaluation.py` (ranking, capacity checks, alternatives)
  - `conflict_resolution.py` (Option/Option logic and client responses)
  - `product_sourcing.py` (missing product handling)
  - `detours.py` (date/requirements/room changes)
  - `messaging.py` (formatting and response assembly)
  - `qna_bridge.py` (general Q&A injection)

#### Step 2 Date Confirmation (`workflows/steps/step2_date_confirmation/trigger/step2_handler.py`)
- Responsibilities: parse/normalize dates, propose candidates, confirm user-selected dates, route HIL approvals, and integrate Q&A.
- Risk: Few top-level functions despite large file size suggests large, nested logic blocks that are hard to test in isolation.
- Suggested split targets:
  - `date_resolution.py` (normalize, parse, candidate generation)
  - `confirmation_flow.py` (state transitions + HIL decisions)
  - `message_formatting.py` (greetings, prompt assembly)
  - `qna_bridge.py` (general Q&A inclusion)

#### Step 1 Intake (`workflows/steps/step1_intake/trigger/step1_handler.py`)
- Responsibilities: intent routing, entity extraction, event creation, dev/test mode branching, room/product detection, detours.
- Risk: A single `process` function handles too many branches, making changes high-risk and debugging slow.
- Suggested split targets:
  - `event_bootstrap.py` (client/event creation + state initialization)
  - `intent_routing.py` (intent classification + entry guards)
  - `entity_merge.py` (entity extraction + profile updates)
  - `detours.py` (date/room/requirements change detection)
  - `qna_bridge.py` (hybrid Q&A)

#### Step 4 Offer (`workflows/steps/step4_offer/trigger/step4_handler.py`)
- Responsibilities: preconditions, pricing inputs, offer composition, HIL acceptance, messaging, and Q&A.
- Risk: Pricing and offer composition are tightly coupled to routing logic, making product schema changes risky.
- Suggested split targets:
  - `preconditions.py` (can we build an offer)
  - `pricing.py` (rebuild pricing inputs, totals)
  - `offer_compose.py` (assemble offer payload + message)
  - `hil_flow.py` (approval preparation)

#### Step 5 Negotiation (`workflows/steps/step5_negotiation/trigger/step5_handler.py`)
- Responsibilities: detect acceptance/rejection, capture billing details, handle change requests, HIL gating.
- Risk: Multiple exit paths and overlapping detection logic cause subtle flow bugs.
- Suggested split targets:
  - `classification.py` (accept/reject/clarify)
  - `billing_capture.py` (billing parsing and persistence)
  - `negotiation_responses.py` (response assembly and HIL setup)

#### Change Propagation (`workflows/change_propagation.py`)
- Responsibilities: detect changed variables, normalize values, and route detours.
- Risk: Coupled detection + routing with many heuristic branches and sparse error handling.
- Suggested split targets:
  - `change_detection.py` (intent + target detection)
  - `change_normalization.py` (date/room normalization)
  - `change_routing.py` (detour routing decisions)
  - `change_disambiguation.py` (clarification prompts)

#### Universal Verbalizer (`ux/universal_verbalizer.py`)
- Responsibilities: prompt building, LLM call, verification, patching, and fallback templates.
- Risk: Hard-fact verification and LLM invocation live together; it is hard to test verification independently.
- Suggested split targets:
  - `prompt_builder.py`
  - `llm_gateway.py` (or reuse a shared gateway)
  - `facts_verifier.py` (extract/verify/patch)
  - `fallback_templates.py`

#### LLM Adapter (`workflows/llm/adapter.py`)
- Responsibilities: provider selection, caching, heuristic overrides, extraction, sanitization.
- Risk: Cache, heuristics, and provider logic are all coupled; hard to reason about correctness.
- Suggested split targets:
  - `payload.py` (payload shaping + cache keys)
  - `provider.py` (provider registry, retries, timeouts)
  - `heuristics.py` (fallbacks and overrides)
  - `sanitizers.py` (sanitized extraction)

#### Orchestrator (`workflow_email.py`)
- Responsibilities: orchestration facade, pre-route pipeline, routing loop, HIL actions.
- Risk: still contains CLI utilities and debug paths; should stay a minimal facade.
- Suggested split targets:
  - move CLI-only helpers into scripts or a dev-only module

#### App Entrypoint (`main.py`)
- Responsibilities: app setup, middleware configuration, startup checks, dev convenience behaviors.
- Risk: import-time side effects (cache deletion, env mutation) and dev-only features embedded in production entrypoint.
- Suggested split targets:
  - `app.py` (production-safe app setup)
  - `main_dev.py` or scripts for dev-only startup actions

## Implementation Plan for Crucial Features

The plan below is ordered by impact on maintainability and scalability. Each feature is sized for PR-friendly execution and aligns with existing refactor scaffolding.

### Feature 1: Entry-Point Separation and Package Layout Normalization

Goal: make production entrypoints deterministic and simplify module imports.

Plan:
1. Create `app.py` as the production-safe FastAPI entrypoint with no side effects.
2. Move dev-only startup logic (cache clearing, auto-launch tools) to `scripts/dev/` or `main_dev.py`.
3. Choose a canonical package structure and update docs/imports accordingly:
   - Option A: move code under a real `backend/` package, and update imports.
   - Option B: keep `workflows`, `api`, `workflow` at top-level and update docs to stop using `backend.*`.
4. Add a small import boundary test to prevent `workflows` from importing `api` directly.

Success criteria:
- Importing the production app has no side effects.
- Docs and imports agree on a single package layout.

### Feature 2: Persistence and Catalog Consolidation

Goal: eliminate data drift and prepare for multi-worker scalability.

Plan:
1. Establish a single DB path constant and ensure steps do not write directly to disk.
2. Consolidate rooms and products into a single canonical data directory with one schema.
3. Centralize data loading in a `data/paths.py` or `workflows/common/data_paths.py` helper.
4. Add a minimal repository interface around the JSON DB to isolate file I/O.

Success criteria:
- One authoritative rooms/products source.
- No step-level direct file writes outside the repository layer.

### Feature 3: Routing and Guard Consolidation

Goal: unify routing decisions and reduce cross-step state mutation.

Plan:
1. Make pre-route decisions purely functional, with a single place applying state changes.
2. Add tests for routing precedence: billing flow, site visit, deposit flow, guard steps.
3. Extract detour logic into a single helper in `workflows/change_propagation` so steps do not re-implement ordering.

Success criteria:
- One authoritative pre-route pipeline.
- Deterministic step selection with tests for critical invariants.

### Feature 4: LLM Gateway and Diagnostics Consolidation

Goal: unify provider usage and ensure safe fallback behavior.

Plan:
1. Create a single LLM gateway (or extend `workflows/llm/adapter.py`) used by all LLM calls.
2. Move direct SDK calls (including the universal verbalizer) behind the gateway.
3. Consolidate fallback diagnostics to a single path with production-safe defaults.

Success criteria:
- One LLM call path with consistent retries/timeouts.
- No diagnostics leaked to user-facing messages unless explicitly enabled.

### Feature 5: God-File Reduction (Step Modules + Change Propagation)

Goal: reduce complexity and make each step maintainable with local tests.

Plan:
1. For Step 1-5 and Step 3 specifically, split by responsibility into small modules.
2. Create thin re-export shims so public imports remain stable.
3. For `change_propagation.py`, isolate detection, normalization, and routing into separate modules.
4. Introduce characterization tests before each split to avoid behavior drift.

Success criteria:
- Each step handler under 800-1,000 lines, with testable submodules.
- Reduced coupling between detection, routing, and rendering logic.

## Suggested PR Order (High Impact First)

1. Feature 1: production-safe entrypoint (`app.py`) + dev-only startup script.
2. Feature 2: data path consolidation + DB path unification.
3. Feature 3: pre-route pipeline invariants + tests.
4. Feature 4: LLM gateway consolidation.
5. Feature 5: step/module decompositions (one step per PR).

## Risks and Open Questions

- Package layout change is high-impact; choose a migration plan and update docs in the same PR.
- Data consolidation requires careful schema mapping to avoid breaking workflows and tests.
- LLM gateway changes may affect quality; add regression tests for hard-facts verification.
- Step splitting should be done with characterization tests to avoid changing flow behavior.

## Next Steps

If you want this to be implemented immediately, pick one of the features above and I will draft a concrete PR checklist with tests for that slice.
