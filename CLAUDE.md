# CLAUDE.md

This file provides guidance to Claude 4.5 working on the OpenEvent-AI repository.

## Your Role

- Act as a senior test- and workflow-focused engineer
- Keep the system aligned with the management plan "Lindy" and Workflow v3/v4 specifications
- Prioritize deterministic backend behaviour and strong automated tests over ad-hoc changes
- Maintain clear documentation of bugs in TEAM_GUIDE.md and new features and changes communicated by me in the chat into the DEV_CHANGELOG.md . Always consult TEAM_GUIDE.md before fixing a bug in case it already existed. 
- For new ideas collected in the chat (often too big to implement in the same task, happy accidents/ideas that happened while fixing another problem) write them to new_features.md in root so we can discuss them later.
- For each new session always re-read the git commits since your last session to stay up to date and DEV_CHANGELOG.md for recent changes. Also reread the workflow v4 in backend workflow/specs/ . 

## Canonical Vocabulary and Concepts

**Use these exact terms (do not invent new ones):**
- Core entities: `msg`, `user_info`, `client_id`, `event_id`, `intent`, `res`, `task`
- Workflow components:
  - OpenEvent Action (light-blue)
  - LLM step (green)
  - OpenEvent Database (dark-blue)
  - Condition (purple)
- Event statuses: `Lead` → `Option` → `Confirmed`
- Workflow steps: Follow documented Workflow v3/v4, especially Steps 1–4 and their detours

## Primary References

**Always open/re-read relevant ones before major changes:**
- AI-Powered Event Management Platform.pdf
- Workflow v3.pdf
- Workflow instance working on Lindy.pdf
- Openevent - Workflow v3 TO TEXT (MAIN).pdf
- Technical Workflow v2.pdf
- workflow_rules.md
- step4_step5_requirements.md
- qna_shortcuts_debugger.md
- TEAM_GUIDE.md (bugs, open issues, heuristics)

## Environment and API Keys

**Never hard-code API keys:**
- Assume OPENAI_API_KEY is provided via environment, possibly sourced from macOS Keychain item "openevent-api-test-key"
- Python code and tests must obtain the key via `backend/utils/openai_key.load_openai_api_key()`, not `os.getenv` directly

**Before running any tests or scripts that call OpenAI:**
1. Activate the dev environment from repo root:
   ```bash
   cd /Users/nico/PycharmProjects/OpenEvent-AI
   source scripts/oe_env.sh
   ```

2. Preferred test commands under this activated environment:
   ```bash
   pytest backend/tests/smoke/test_workflow_v3_agent.py -q
   pytest backend/tests_integration/test_e2e_live_openai.py -q
   # and other pytest commands
   ```

## Debugger and Conversation Traces

**The OpenEvent debugger provides real-time tracing of all workflow activity. Use it to understand what happened during any conversation thread.**

### Enabling Debug Traces

Debug tracing is enabled by default. Control via environment variable:
```bash
DEBUG_TRACE=1  # Enable (default)
DEBUG_TRACE=0  # Disable
```

### Live Log Files (Recommended for AI Agents)

**The fastest way to see what's happening in a conversation** is to tail the live log file:

```bash
# Watch a specific thread in real-time
tail -f tmp-debug/live/{thread_id}.log

# List all active threads with live logs
curl http://localhost:8000/api/debug/live

# Get live log content via API
curl http://localhost:8000/api/debug/threads/{thread_id}/live
```

Live logs are:
- **Human-readable** — Simple timestamp + event format
- **Real-time** — Written as events happen
- **Auto-cleaned** — Deleted when thread closes

Example live log output:
```
[14:23:01] >> ENTER Step1_Intake
[14:23:01] Step1_Intake | LLM IN (classify_intent): Subject: Private Dinner...
[14:23:02] Step1_Intake | LLM OUT (classify_intent): {"intent": "event_request"...
[14:23:02] Step1_Intake | GATE PASS: email_present (1/2)
[14:23:02] Step1_Intake | CAPTURED: participants=30
[14:23:02] Step1_Intake | STATE: date=2026-02-14, date_confirmed=True
[14:23:02] << EXIT Step1_Intake
```

### Debug API Endpoints

When debugging issues, access conversation traces via these endpoints:

| Endpoint | Purpose |
|----------|---------|
| `/api/debug/live` | **List active threads with live logs** |
| `/api/debug/threads/{thread_id}/live` | **Get live log content** |
| `/api/debug/threads/{thread_id}` | Full trace with state, signals, timeline |
| `/api/debug/threads/{thread_id}/timeline` | Timeline events only |
| `/api/debug/threads/{thread_id}/report` | Human-readable debug report |
| `/api/debug/threads/{thread_id}/llm-diagnosis` | LLM-optimized diagnosis |
| `/api/debug/threads/{thread_id}/timeline/download` | Download JSON export |
| `/api/debug/threads/{thread_id}/timeline/text` | Download text export |

### LLM Diagnosis Endpoint

**Most important for AI debugging:** The `/api/debug/threads/{thread_id}/llm-diagnosis` endpoint returns a structured, LLM-optimized format including:
- Quick status (date, room, hash, offer confirmation)
- Problem indicators (hash mismatches, detour loops, gate failures)
- Last 5 events with summaries
- Key state values

Example usage:
```bash
curl http://localhost:8000/api/debug/threads/{thread_id}/llm-diagnosis
```

### Frontend Debugger

Access the visual debugger at `http://localhost:3000/debug` which provides:
- Thread selection and status overview
- Detection view (intent classification, entity extraction)
- Agents view (LLM prompts and responses)
- Errors view (auto-detected problems)
- Timeline view (full event timeline)
- Dates view (date value transformations)
- HIL view (human-in-the-loop tasks)

### Trace Event Types

The tracer captures these event types:
- `STEP_ENTER`/`STEP_EXIT` — Step transitions
- `GATE_PASS`/`GATE_FAIL` — Gate evaluations with inputs
- `DB_READ`/`DB_WRITE` — Database operations
- `ENTITY_CAPTURE`/`ENTITY_SUPERSEDED` — Entity lifecycle
- `DETOUR` — Step detours with reasons
- `QA_ENTER`/`QA_EXIT`/`GENERAL_QA` — Q&A flow
- `DRAFT_SEND` — Draft messages
- `AGENT_PROMPT_IN`/`AGENT_PROMPT_OUT` — LLM prompts and responses

### Key Files

| File | Purpose |
|------|---------|
| `backend/debug/live_log.py` | **Human-readable live logs** (recommended for AI agents) |
| `backend/debug/trace.py` | Core trace event bus and emit functions |
| `backend/debug/hooks.py` | Trace decorators and helpers |
| `backend/debug/reporting.py` | Report generation and LLM diagnosis |
| `backend/debug/timeline.py` | Timeline persistence (JSONL format) |
| `backend/debug/state_store.py` | State snapshot store |

## Behaviour Around Bugs and Features

### Before Fixing a Bug

1. **Read TEAM_GUIDE.md** and search for a matching bug description
2. If it exists, update that entry with:
   - Current status (open / investigating / fixed)
   - File(s) touched
   - Test(s) covering it (paths and test names)
3. If it does not exist, add a new entry under "Bugs and Known Issues" with:
   - Short title
   - Description
   - Minimal reproduction scenario

### After Fixing a Bug

1. Add or update automated tests so the bug cannot silently reappear
2. Mark the bug as fixed in TEAM_GUIDE.md, referencing the tests that now cover it

### For New Features, Refactors and Changes

Maintain a lightweight log in DEV_CHANGELOG.md at repo root:
- Date (YYYY-MM-DD)
- Short description
- Files touched
- Tests added/updated

newest entries at the top.

## Testing Principles (High Priority)

**The test suite is the main guardrail; keep it clean, well-structured and focused on high-value behaviours.**

- Prefer pytest with clear naming and structure
- Tests should be organized for easy discovery:
  - Detection tests (Q&A, confirmation, shortcuts, special manager request, detours)
  - Workflow tests (Steps 1–4, Status Lead/Option/Confirmed, gatekeeping)
  - Q&A and general shortcuts
  - GUI/frontend/chat integration where applicable

**For each major detection type in the workflow, strive to have:**
- A happy-path test
- One or more edge-case tests

**Always add tests for:**
- Regressions mentioned in TEAM_GUIDE.md
- Known fallback/stub issues
- Detours and conflict logic

## Fallback and "Old Default" Behaviour

**Main goal: Prevent the system from silently falling back to old stub responses or generic defaults.**

When you see code paths that:
- Emit very generic messages ("sorry, cannot handle this request" or old templates)
- Or bypass the current Workflow v3/v4 logic

Add assertions or tests so that such paths are detectable and fail loudly in tests.

**When writing or updating tests:** Add expectations so that if a fallback/stub message appears in a flow that should be handled deterministically, the test fails.

## Working Style

- Always explain in plain language what you are doing and why, but keep responses concise
- Use the existing workflow files and terminology exactly; do not invent new step names or statuses
- Prefer minimal, targeted changes over large refactors

**For any non-trivial change to tests or workflow logic:**
- State the relevant workflow rule or document you are following
- Outline the tests you will add/update
- Ensure that running pytest under scripts/oe_env.sh will validate your work

## When in Doubt

- Re-read Workflow v3 TO TEXT , FRONTEND_REFERENCE.md and TEAM_GUIDE.md
- Prefer adding or strengthening tests before changing logic
- If something feels like a "shortcut", check shortcut_workflow_request.txt and qna_shortcuts_debugger.md before proceeding

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

## Workflow Architecture (V3/V4 Authoritative)

**Sources of Truth:**
- Workflow v3 documents (see Primary References above)
- `backend/workflow/specs/` contains v4 workflow specifications:
  - `v4_dag_and_change_rules.md` - Dependency graph and minimal re-run matrix
  - `no_shortcut_way_v4.md` - Complete state machine with entry guards
  - `v4_shortcuts_and_ux.md` - Shortcut capture policy and UX guarantees
  - `v4_actions_payloads.md` - Action/payload contracts

### Canonical State Variables

The workflow maintains these core variables:
- `chosen_date` and `date_confirmed` (boolean)
- `requirements = {participants, seating_layout, duration(start-end), special_requirements}`
- `requirements_hash` (SHA256 of requirements)
- `locked_room_id` (null until room confirmed)
- `room_eval_hash` (snapshot of requirements_hash used for last room check)
- `selected_products` (catering/add-ons)
- `offer_hash` (snapshot of accepted commercial terms)
- `caller_step` (who requested the detour)

### Dependency DAG

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
db.events.sync_lock(event_id)                         # [DB-READ/WRITE]
db.events.set_lost(event_id)                          # [DB-WRITE]
db.events.set_confirmed(event_id)                     # [DB-WRITE]

# Date & room operations
db.dates.next5(base_or_today, rules)                  # [DB-READ]
db.rooms.search(date, requirements)                   # [DB-READ]

# Product & offer operations
db.products.rank(rooms, wish_list)                    # [DB-READ]
db.offers.create(event_id, payload)                   # [DB-WRITE]

# Options & policy
db.options.create_hold(event_id, expiry)              # [DB-WRITE]
db.policy.read(event_id)                              # [DB-READ]
```

### LLM Integration

**Adapters:** `backend/workflows/llm/adapter.py` routes to providers in `backend/llm/providers/`
- Intent classification, entity extraction, draft composition all pass curated JSON
- Drafts remain HIL-gated before outbound send
- Profile selection via `backend/config.py` reading `configs/llm_profiles.json`

**LLM Role Separation:**

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

**Testing:** Tests in `tests/stubs/` provide deterministic LLM responses for regression tests but do not reflect live behaviour of agent using OpenAI key. So always test with real openai key mimicking real user flow as it happens in the real world (not just backend but UX and user perspective). The challenge of this application is making it generally useful and not having to specifically hardcode each new scenario. We are looking for a sustainable , long and general solution for all kind of client responses (focusing on 2 languages for now but planning multilingual usage for the future).

## Important Implementation Notes

**Thread Safety:** Database operations use `FileLock` (in `backend/workflows/io/database.py`). Always use provided helpers (`load_db`, `save_db`) rather than direct JSON access.

**Idempotency:** Re-confirming the same date or re-running availability checks is safe. System checks latest audit log entries to avoid duplicate work.

**Hash Invalidation:** When requirements change (participants, duration, room preference), `requirements_hash` updates, invalidating `room_eval_hash`. Step 3 must re-run for HIL approval.

**Time Handling:** All dates use Europe/Zurich timezone. Tests use `freezegun` for deterministic time (`tests/utils/timezone.py`).

**Detour Recovery:** After detour (e.g., Step 3 → Step 2 for new date → Step 3), system preserves all prior metadata and only re-runs dependent steps.

**Open Decisions:** Write questions which arent clear regarding logic, UX into docs/internal/OPEN_DECISIONS.md and docs/integration_to_frontend_and_database/MANAGER_INTEGRATION_GUIDE.md 

**Git Commits:** For longer session where you complete multiple tasks , always add a git commit after every fully completed task and I will push that later when the session is over. This helps me track your progress and revert specific changes if needed.

## Common Gotchas

1. **macOS .pyc Permission Issues:** Run with `python -B` or set `PYTHONDONTWRITEBYTECODE=1`
2. **Missing Calendar Data:** Missing `calendar_data/<id>.json` means room is always free
3. **Step Skipping:** Workflow enforces strict prerequisites; cannot skip to Step 5 without completing Steps 1-4
4. **Hash Mismatches:** If `room_eval_hash` doesn't match `requirements_hash`, Step 3 blocks until re-approved
5. **Pytest Test Selection:** Default runs `v4` tests only; use `-m "v4 or legacy"` to include all
6. **LLM Stub vs Live:** Tests in `tests/stubs/` use stubbed LLM responses; always validate critical flows with live OpenAI key mimicking real client interactions from workflow start to end (offer confirmation).
