# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

OpenEvent is an AI-powered venue booking workflow system for The Atelier. It automates the end-to-end booking flow from client email intake through event confirmation, maintaining deterministic state across a 7-step workflow with human-in-the-loop (HIL) approvals.

**Architecture:** Monorepo with Python FastAPI backend + Next.js frontend, driven by a deterministic workflow engine that gates AI responses through HIL checkpoints.

## Development Commands

### Backend (Python FastAPI)
```bash
# Start backend server (from repo root)
export PYTHONDONTWRITEBYTECODE=1  # optional, prevents .pyc permission issues on macOS
uvicorn backend.main:app --reload --port 8000

# Run specific workflow step manually
python -B backend/availability_pipeline.py <EVENT_ID>
```

### Frontend (Next.js)
```bash
# Start frontend dev server (from repo root)
npm run dev
# Opens at http://localhost:3000

# In atelier-ai-frontend directory
npm run dev      # dev with turbopack
npm run build    # production build
npm run start    # production server
npm test         # vitest
```

### Testing

**Primary test suite (v4 workflow tests):**
```bash
# Run default v4 tests (excludes legacy)
pytest

# Run specific workflow alignment tests (Steps 1-3)
pytest tests/specs/

# Run end-to-end v4 tests
pytest tests/e2e_v4/

# Run regression suite
pytest tests/regression/

# Run legacy v3 alignment tests (if needed)
pytest -m legacy

# Run all tests including legacy
pytest -m "v4 or legacy"

# Run single test
pytest tests/e2e_v4/test_happy_path.py::test_intake_to_confirmation -v
```

**CI/stub mode (auto-selects live or stubbed LLM):**
```bash
./scripts/run_ci_or_stub.sh
```

Test markers are defined in `pytest.ini`:
- `v4`: Current workflow tests (default)
- `legacy`: Legacy v3 alignment tests

### Dependencies
```bash
# Python (backend)
pip install -r requirements-dev.txt  # test dependencies
# Main dependencies are inferred from imports (fastapi, uvicorn, pydantic)

# Frontend
cd atelier-ai-frontend && npm install
```

## Workflow Architecture (V4 Authoritative)

**Source of Truth:** `backend/workflow/specs/` contains v4 workflow specifications:
- `v4_dag_and_change_rules.md` - Dependency graph and minimal re-run matrix
- `no_shortcut_way_v4.md` - Complete state machine with entry guards
- `v4_shortcuts_and_ux.md` - Shortcut capture policy and UX guarantees
- `v4_actions_payloads.md` - Action/payload contracts

### Canonical State Variables

The workflow maintains these core variables (see `v4_dag_and_change_rules.md`):
- `chosen_date` and `date_confirmed` (boolean)
- `requirements = {participants, seating_layout, duration(start-end), special_requirements}`
- `requirements_hash` (SHA256 of requirements)
- `locked_room_id` (null until room confirmed)
- `room_eval_hash` (snapshot of requirements_hash used for last room check)
- `selected_products` (catering/add-ons)
- `offer_hash` (snapshot of accepted commercial terms)
- `caller_step` (who requested the detour)

### Dependency DAG (V4)

```
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
```

**Key Insight:** Room evaluation depends on confirmed date AND current requirements. Offer depends on room decision (unchanged room_eval_hash) plus products. Confirmation depends on accepted offer. This drives the "detour and return" logic with hash guards to prevent redundant re-checks.

### Minimal Re-Run Matrix (What Actually Re-Executes)

| Client Change | Re-run Exactly | Skip | Guard That Decides |
|---|---|---|---|
| **Date** | Step 2 (Date Confirmation). If new date confirmed and room search still required, Step 3; otherwise return to caller. | Products, offer, negotiation (unless room outcome changes) | `date_confirmed` re-set; Step 2 owns date |
| **Room (different/bigger)** | Step 3 (Room Availability) only; then return to caller (often Step 4) | Step 2; products | Step-3 entry guard B ("client asks to change room"); `room_eval_hash` refreshed |
| **Requirements (participants/layout/duration/special)** | Step 3 re-evaluates room fit; then back to caller | Step 2 | Step-3 entry guard C + `requirements_hash ≠ room_eval_hash` triggers re-check |
| **Products/Catering** | Stay inside Step 4 (products mini-flow → offer rebuild); no date/room recheck | Steps 2-3 | Products live in Step 4; no structural dependency upward |
| **Commercial terms only** | Step 5 (Negotiation) only; accept → Step 7; else loop | Steps 2-3-4 (unless negotiation implies structural change) | Negotiation routing and acceptance handoff |
| **Deposit/Reservation** | Within Step 7 (option/deposit branches) | Steps 2-4 | Confirmation layer owns payment/option lifecycle |

### Deterministic Detour Rules

1. **Always set `caller_step` before jumping**
2. **Jump to the owner step** of the changed variable:
   - Date → Step 2
   - Room/Requirements → Step 3
   - Products/Offer consistency → Step 4
3. **On completion, return to `caller_step`**, unless hash check proves nothing changed (fast-skip)
4. **Hashes prevent churn:**
   - If `requirements_hash` unchanged, skip room re-evaluation
   - If `offer_hash` still matches, skip transition repairs

```
[ c a l l e r ] ──(change detected)──► [ owner step ]
▲                                           │
└──────────(resolved + hashes)──────────────┘
```

### Entry Guard Prerequisites (Step-by-Step)

**→ Step 2 (Date):** `event_id` exists; email known; date **not** confirmed

**→ Step 3 (Room):** `date_confirmed=true`, capacity present, requirements present; `requirements_hash` computed

**→ Step 4 (Offer compose/send):**
- **P1:** `date_confirmed`
- **P2:** `locked_room_id` AND `requirements_hash == room_eval_hash`
- **P3:** capacity present
- **P4:** products phase completed (or explicitly skipped)

**First unmet prerequisite triggers detour:**
- P1 fails → detour to Step 2 (caller_step=4)
- P2 or P3 fail → detour to Step 3 (caller_step=4)
- P4 incomplete → products mini-flow

**All client-facing sends need HIL approval** except the tight products mini-loop.

### 7-Step Pipeline (Implementation Locations)

1. **Step 1 - Intake** (`backend/workflows/groups/intake/`):
   - [LLM-Classify] intent, [LLM-Extract] entities (Regex→NER→LLM)
   - Loops: ensure email present, date complete (Y-M-D), capacity present (int)
   - Captures `wish_products` for ranking (non-gating)
   - **Never re-runs post-creation** (HIL edits only)

2. **Step 2 - Date Confirmation** (`backend/workflows/groups/date_confirmation/`):
   - Calls `db.dates.next5` with **TODAY (Europe/Zurich)** ≥ TODAY, blackout/buffer rules
   - Presents none/one/many-feasible flows via [LLM-Verb] → [HIL] → send
   - Parses client reply [LLM-Extract] → ISO date
   - On confirmation: `db.events.update_date`, sets `date_confirmed=true`

3. **Step 3 - Room Availability** (`backend/workflows/groups/room_availability/`):
   - Entry guards: A (no room), B (room change request), C (requirements change)
   - Calls `db.rooms.search(chosen_date, requirements)` → branches:
     - Available: [LLM-Verb] → [HIL] → on "proceed" → `db.events.lock_room(locked_room_id, room_eval_hash=requirements_hash)`
     - Option: explain option → [HIL] → accept option or detour to Step 2
     - Unavailable: propose date/capacity change → detour to Step 2 (caller_step=3) or loop on req change

4. **Step 4 - Offer** (`backend/workflows/groups/offer/`):
   - Validates P1-P4; detours if any fail
   - Products mini-flow:
     - ≤5 rooms: [LLM-Verb] table (confirmed + up to 5 alts), rank by `wish_products` fulfillment
     - >5 rooms: ask "specific products/catering?", re-rank via `db.products.rank`
     - Special requests → [HIL] decide → loop until approved or denied
   - Compose: [LLM-Verb] professional offer + totals → [HIL] approve
   - Send: `db.offers.create(status=Lead)` → `offer_id`

5. **Step 5 - Negotiation** (`backend/workflows/groups/negotiation_close.py`):
   - Interprets accept/decline/counter/clarification
   - Structural changes route back to Steps 2/3/4 via detours
   - Accept → hands off to Step 7

6. **Step 6 - Transition Checkpoint** (`backend/workflows/groups/transition_checkpoint.py`):
   - Validates all prerequisites before Step 7
   - Sets `transition_ready` flag

7. **Step 7 - Confirmation** (`backend/workflows/groups/event_confirmation/`):
   - Manages site visits, deposits, reserves, declines, final confirmations
   - Option/deposit branches via `db.policy.read`, `db.options.create_hold`
   - All transitions audited through HIL gates

### Shortcut Capture Policy (V4)

**No Shortcut Way (orchestration):** Advance strictly via gates (Intake → Date → Room → Products/Offer). Shortcuts **never skip gates**.

**Shortcut Way (capture):** Eagerly capture relevant entities **out of order** and reuse at their owning step **without re-asking**, if valid and unchanged.

**Deterministic Rules:**
1. **Eager capture:** Run Regex → NER → LLM-refine on every message. Persist with `source="shortcut"`, `captured_at_step`
2. **Validation:** Apply owning step's validator (capacity: positive int; date: ISO Y-M-D). If invalid/ambiguous, **don't persist** (owning step will ask)
3. **No re-ask:** At owning step, if valid shortcut exists and client hasn't changed it, **use silently**
4. **Change detection:** New value supersedes prior, recomputes hashes, detours **only dependent steps**
5. **Precedence:** Values at owning step override shortcuts
6. **Never skip gates:** Shortcut presence doesn't allow early entry; P1-P4 and entry guards still apply

**Examples:**
- Capacity stated at Intake → stored as shortcut → Step 3 won't ask capacity again
- "Projector" mentioned at Intake → stored in `wish_products` → Step 4 uses for ranking

### UX Footer Contract (Never Left in the Dark)

**Every outbound message must include:**
```
Step: <StepName> · Next: <expected action/options> · State: <Awaiting Client|Waiting on HIL>
```

This footer keeps clients and HIL aligned on progress, upcoming actions, and wait states.

### Event Status Lifecycle

- **Lead** → **Option** → **Confirmed** → **Cancelled**
- Stored in `event.metadata.status` and mirrored to `event.event_data` for legacy compatibility

### Thread State

Tracks sub-step position within each step (e.g., `AwaitingClient`, `WaitingOnHIL`, `Closed`)

### Three Crisp Change Scenarios (End-to-End)

**A) Client ups attendees 24→36 (same date):**
- Step-3 entry guard C triggers
- Re-evaluate rooms via `db.rooms.search`
- If room still fits, return to caller (often Step 4) **without touching date/products**

**B) Client changes date after offer sent:**
- `caller_step=Step 4` → detour to Step 2
- Confirm new date → if same room still valid, **skip Step 3** and return to Step 4 to refresh offer dates
- Else run Step 3, then back to Step 4

**C) Client accepts but adds Prosecco:**
- Stay in Step 4 products sub-flow → recompute totals
- Resend offer or proceed if already accepted/within policy → Step 7 for final confirmation/deposit
- **No date/room rechecks**

### Database & Persistence

**Primary Database:** `backend/events_database.json` (FileLock-protected JSON store)

Schema managed by `backend/workflows/io/database.py`:
- `clients`: Client profiles keyed by lowercased email
- `events`: Event records with metadata, requirements, thread_state, audit logs
- `tasks`: HIL approval tasks (date confirmation, room approval, offer review, etc.)

**DB Adapter Surface (Engine Only; NEVER LLM)**

The workflow engine calls these adapters. **LLM never touches DB directly:**

```python
# Event lifecycle
db.events.create(intake)                              # [DB-WRITE] → event_id
db.events.update_date(event_id, date)                 # [DB-WRITE]
db.events.lock_room(event_id, room_id, room_eval_hash) # [DB-WRITE]
db.events.sync_lock(event_id)                         # [DB-READ/WRITE] (date/room/hashes/products/totals)
db.events.set_lost(event_id)                          # [DB-WRITE]
db.events.set_confirmed(event_id)                     # [DB-WRITE]

# Date & room operations
db.dates.next5(base_or_today, rules)                  # [DB-READ] (≥ TODAY(Europe/Zurich), blackout/buffer rules)
db.rooms.search(date, requirements)                   # [DB-READ]

# Product & offer operations
db.products.rank(rooms, wish_list)                    # [DB-READ]
db.offers.create(event_id, payload)                   # [DB-WRITE] (status=Lead → offer_id)

# Options & policy
db.options.create_hold(event_id, expiry)              # [DB-WRITE]
db.policy.read(event_id)                              # [DB-READ] (deposit required?)
```

**Privacy Model:**
- Clients keyed by lowercased email for per-user isolation
- Context snapshots include: profile + last 5 history previews + latest event (no cross-user leakage)
- History previews capped at 160 chars, store intent/confidence only
- All database helpers filter by current email (`last_event_for_email`, `find_event_idx`)

### LLM Integration

**Adapters:** `backend/workflows/llm/adapter.py` routes to providers in `backend/llm/providers/`
- Intent classification, entity extraction, draft composition all pass curated JSON
- Drafts remain HIL-gated before outbound send
- Profile selection via `backend/config.py` reading `configs/llm_profiles.json`

**LLM Role Separation (V4 Pattern):**

The workflow uses three distinct LLM roles, each with strict boundaries:

1. **[LLM-Classify]** - Intent classification
   - Determines message intent (inquiry, accept, counter, etc.)
   - Returns structured classification result
   - Used at intake and throughout negotiation

2. **[LLM-Extract]** - Entity extraction (Regex→NER→LLM pipeline)
   - First attempt: Regex patterns for common formats
   - Fallback: NER (Named Entity Recognition)
   - Final refinement: LLM extraction with validation
   - Examples: dates (ISO Y-M-D), capacity (positive int), products, special requirements
   - **NEVER directly accesses database** - only processes text

3. **[LLM-Verb]** - Verbalization/draft composition
   - Composes professional client-facing messages
   - Takes structured data from workflow engine as input
   - Outputs draft messages for HIL approval
   - Examples: date options, room availability, offer composition
   - All drafts go through HIL gate before sending (except tight products loop)

**Critical Boundary:** LLM adapters receive curated JSON payloads from the workflow engine and NEVER call database functions directly. All DB operations flow through the engine's adapter surface.

**Environment Variables:**
- `AGENT_MODE`: `openai` (live) or `stub` (testing)
- `OE_LLM_PROFILE`: Profile name from `configs/llm_profiles.json`
- `OPENAI_API_KEY`: Set via environment or macOS Keychain (see `scripts/run_ci_or_stub.sh`)

**Stubbed Testing:** Tests in `tests/stubs/` provide deterministic LLM responses for regression tests

### Room & Calendar System

**Room Configuration:** `backend/rooms.json` defines capacities, buffers, calendar IDs

**Calendar Adapters:** `backend/adapters/calendar_adapter.py` reads busy slots from `backend/calendar_data/<calendar_id>.json`

**Availability Logic:** `backend/workflows/groups/room_availability/trigger/process.py` computes:
- Direct conflicts (event overlaps busy slot)
- Buffer violations (±30/60/90 min near-miss)
- Fallback alternatives (if preferred room unavailable)

### Frontend Architecture

**Location:** `atelier-ai-frontend/` (Next.js 14+ with App Router)

**Key Routes:**
- `/` - Client chat interface
- Event Manager UI (exact routes TBD from app structure)

**Integration:** Calls FastAPI backend at `http://localhost:8000` for chat/workflow operations

## Common Development Patterns

### Adding a New Workflow Step

1. Create step directory in `backend/workflows/groups/<step_name>/`
2. Implement `trigger/process.py` with function signature matching `GroupResult`
3. Register in `backend/workflow_email.py` step router (around L150-300)
4. Add entry guards in `backend/workflow/guards.py` if prerequisites needed
5. Update `WorkflowStep` enum in `backend/workflow/state.py`
6. Add test fixtures in `tests/fixtures/` and tests in `tests/specs/<step_name>/`

### Working with Event State

```python
from backend.workflows.io.database import load_client_context, update_event_metadata

# Load bounded client context (no cross-user leakage)
ctx = load_client_context(email="client@example.com")
event = ctx["last_event"]

# Update event metadata atomically
update_event_metadata(
    email="client@example.com",
    event_id=event["event_id"],
    updates={"locked_room_id": "room_a", "room_eval_hash": "<hash>"}
)
```

### Creating HIL Tasks

```python
from backend.workflows.io.tasks import enqueue_task

enqueue_task(
    email="client@example.com",
    event_id="evt_123",
    task_type="room_approval",  # TaskType enum value
    payload={"room_id": "room_a", "date": "2025-03-15", "draft_reply": "..."}
)
```

### Running Specific Workflow Scenarios

```bash
# Use manual scenario scripts for targeted testing
python scripts/manual_ux_scenario_E.py  # Tests specific UX flow E
python scripts/manual_smoke_intake.py    # Smoke test intake step
```

## Debugging & Tracing

**Enable Debug Mode:**
```bash
export WF_DEBUG_STATE=1  # Prints state transitions to console
```

**Debug Artifacts:**
- `tmp-debug/sessions/` - Session traces
- `tmp-debug/reports/` - Generated reports
- `backend-uvicorn.log` - Backend server logs

**Debug API Endpoints** (`backend/api/debug.py`):
- `/debug/trace/<thread_id>` - Full execution trace
- `/debug/timeline/<thread_id>` - Timeline view
- `/debug/report/<thread_id>` - Generated report

## Git Workflow

**Main branch:** `main`
**Current feature branch:** `feature/agent-workflow-ui-2`

**Common branches:**
- Feature branches: `feature/*`
- Chores: `chore/*`

## File Organization Patterns

```
backend/
  workflows/
    groups/          # Step implementations
    common/          # Shared types, prompts, payloads
    io/              # Database & task persistence
    llm/             # LLM adapter layer
    nlu/             # Natural language understanding utilities
    planner/         # Smart shortcuts & planning
    qna/             # General Q&A handling
  adapters/          # External service adapters (calendar, GUI)
  domain/            # Core domain models (EventStatus, TaskStatus, etc.)
  api/               # FastAPI route definitions
  tests/             # Backend-specific tests (currently just smoke/)

tests/               # Main test suite (repo root)
  specs/             # Spec-driven workflow tests
  e2e_v4/            # End-to-end v4 tests
  regression/        # Regression suite
  fixtures/          # Test data fixtures
  stubs/             # Stubbed LLM responses
  _legacy/           # Legacy v3 tests

atelier-ai-frontend/
  app/               # Next.js App Router pages
  components/        # React components
  agent/             # Frontend agent logic
```

## Important Implementation Notes

**Thread Safety:** Database operations use `FileLock` (in `backend/workflows/io/database.py`). Always use provided helpers (`load_db`, `save_db`) rather than direct JSON access.

**Idempotency:** Re-confirming the same date or re-running availability checks is safe. System checks latest audit log entries to avoid duplicate work.

**Hash Invalidation:** When requirements change (participants, duration, room preference), `requirements_hash` updates, invalidating `room_eval_hash`. Step 3 must re-run for HIL approval.

**Time Handling:** All dates use Europe/Zurich timezone. Tests use `freezegun` for deterministic time (`tests/utils/timezone.py`).

**Detour Recovery:** After detour (e.g., Step 3 → Step 2 for new date → Step 3), system preserves all prior metadata and only re-runs dependent steps.

## Test Data & Fixtures

**Calendar Fixtures:** Place in `backend/calendar_data/<calendar_id>.json`
```json
{
  "busy": [
    {"start": "2025-10-16T13:45:00+02:00", "end": "2025-10-16T16:30:00+02:00"}
  ]
}
```

**Event Database:** `backend/events_database.json` (auto-managed, do not edit manually)

**Test Fixtures:** `tests/fixtures/` contains deterministic test cases for each workflow step

## Common Gotchas

1. **macOS .pyc Permission Issues:** Run with `python -B` or set `PYTHONDONTWRITEBYTECODE=1`
2. **Missing Calendar Data:** Missing `calendar_data/<id>.json` means room is always free
3. **Step Skipping:** Workflow enforces strict prerequisites; cannot skip to Step 5 without completing Steps 1-4
4. **Hash Mismatches:** If `room_eval_hash` doesn't match `requirements_hash`, Step 3 blocks until re-approved
5. **Pytest Test Selection:** Default runs `v4` tests only; use `-m "v4 or legacy"` to include all