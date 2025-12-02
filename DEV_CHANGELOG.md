# Development Changelog

## 2025-12-02

### Dynamic Content Abbreviation for Non-Q&A Paths

**Task: Generalize content abbreviation for menu/catering display**

Extended the content abbreviation system (previously only in room_availability for Q&A) to work for all workflow steps that display detailed menu/catering information.

**Problem Solved:**
- Date confirmation step was showing full menu descriptions (640+ chars) directly in chat
- Only room_availability had threshold-based abbreviation with links
- No way to build link parameters from workflow state (only from Q&A q_values)

**Implementation:**

1. **Shared Short Format** (`backend/workflows/common/menu_options.py`)
   - Added `format_menu_line_short()` — abbreviated format (name + price only, no description)
   - Added `MENU_CONTENT_CHAR_THRESHOLD = 400` — UX standard threshold
   - Exported in `__all__` for reuse across workflow steps

2. **Date Confirmation Update** (`backend/workflows/groups/date_confirmation/trigger/process.py`)
   - Updated `_append_menu_options_if_requested()` to:
     - Check content length against threshold
     - Build link params from workflow state (event_entry, user_info, menu_request)
     - Use abbreviated format when exceeding threshold
     - Always include catering info page link for reference

3. **Room Availability Refactor** (`backend/workflows/groups/room_availability/trigger/process.py`)
   - Removed local `_short_menu_line()` function
   - Now uses shared `format_menu_line_short()` from menu_options
   - `QNA_SUMMARY_CHAR_THRESHOLD` now references shared constant

**Link Parameter Sources (non-Q&A path):**
- `event_entry.chosen_date` or `month_hint` → date/month
- `requirements.number_of_participants` → capacity
- `menu_request.vegetarian/wine_pairing/three_course` → dietary/course filters

**New Tests:**
- `tests/workflows/test_menu_abbreviation.py` — 14 tests covering:
  - Short format output validation
  - Threshold behavior (full exceeds, short stays under)
  - Link generation with query params
  - Menu request extraction

**Key Files Changed:**
- `backend/workflows/common/menu_options.py`
- `backend/workflows/groups/date_confirmation/trigger/process.py`
- `backend/workflows/groups/room_availability/trigger/process.py`
- `tests/workflows/test_menu_abbreviation.py` (new)

---

### Site Visit Implementation with Change Management

**Task: Enhanced site visit implementation plan with update/change/detour logic**

Extended the site visit functionality to support comprehensive change management:

**Key Enhancements:**
1. **Change Detection System**
   - Pattern-based detection for "change site visit", "reschedule", "cancel" requests
   - Change type classification: date, room, both, or cancel
   - Distinguishes changes from new requests

2. **Dependency Validation**
   - Room changes: validates new room on current date
   - Date changes: validates current room on new date
   - Both changes: suggests changing one at a time if conflict
   - Enforces constraint: site visit must be before main event

3. **Fallback Suggestions**
   - When requested change invalid, provides alternatives
   - Shows available dates for requested room
   - Shows available rooms for requested date

4. **Calendar Updates**
   - Updates existing calendar entry on changes
   - Cancels calendar entry on cancellation
   - Maintains change history for audit

**New/Updated Documentation:**
- `implementation_plans/site_visit_implementation_plan.md` — Phases 7-9 added for change management
- `backend/workflows/specs/site_visit_dag.md` — Created comprehensive DAG documentation

**Implementation Additions:**
- Site visit change detector patterns
- Dependency validation matrix
- Change application with conflict resolution
- Test cases for all change scenarios

**Frontend:**
- Created `/atelier-ai-frontend/app/info/site-visits/page.tsx` — Site visit information page
- Updated `backend/utils/pseudolinks.py` — Added site visit link generators

---

### Links, Test Pages, and Q&A Shortcuts

**Implemented**
- Added pseudolink utilities plus calendar logging stubs, and exposed `/api/test-data/*` endpoints with room, catering, and Q&A payloads (including full menus for long-form references).
- Built info pages for rooms, catering catalog/detail, and FAQ; rooms now show manager-configured items, prices, and room-specific catering menus (placeholder: all menus) with working links.
- Updated room-availability workflow to prepend a rooms-page link and to instruct the verbalizer to summarize long Q&A payloads with a shortcut link once text exceeds a 400-character threshold (tracked in `state.extras`, also embedded as a verbalizer note). Catering Q&A always includes the full-menu page link.

**UX**
- Dates on room pages now use month abbreviations (e.g., Sept).
- Q&A page renders full catering menus for Catering category requests so long answers can be offloaded to the page.

**Open TODO / Testing**
- Verbalizer still needs a dedicated path to honor the Q&A shortcut hint beyond inline instructions.
- Mapping of menus to rooms is currently a placeholder (all menus on all rooms) until manager-driven assignments are surfaced from the DB.
- Tests not run in this change set.

## 2025-12-01

### Site Visit Implementation Planning

**Task: Created implementation plan for site visit functionality**

Designed a comprehensive system for handling venue site visits as a Q&A-like thread that branches off from the main workflow:

**Key Features:**
1. **Detection System**
   - Pattern-based detection for "site visit", "venue tour", "viewing" requests
   - Distinguishes actual requests from Q&A about visits
   - Confidence scoring with room/date extraction

2. **Thread Architecture**
   - Site visits work like Q&A threads - branch off, complete, return to main flow
   - Gatekeeping: requires room (default from main flow) and date
   - Date constraints: before main event if date confirmed, otherwise any future date

3. **Smart Defaults**
   - Uses locked room from main flow if available
   - Client can override with explicit room mention
   - Proposes available weekday slots

4. **Calendar Integration**
   - Creates separate calendar entries with status="Option"
   - Tracks site visits independently from main event

**New Documentation:**
- `implementation_plans/site_visit_implementation_plan.md` — Complete implementation guide

**Proposed Architecture:**
- Site visit detector: `/backend/workflows/nlu/site_visit_detector.py`
- Thread manager: `/backend/workflows/threads/site_visit_thread.py`
- Frontend info page: `/app/info/site-visits/page.tsx`
- Integration with all workflow steps

**Key Design Decisions:**
- Site visit detection happens BEFORE general Q&A (no conflicts)
- Clear separation of visit dates/rooms from main event
- Seamless return to main flow with confirmation message
- Shortcuts allowed (confirm directly from proposed options)

**Implementation Phases:**
1. Detection & classification system
2. Thread management with gatekeeping
3. Workflow integration (all steps)
4. Frontend information pages
5. Testing suite

---

### Pseudolinks & Calendar Integration Planning

**Task: Created implementation plans for links/pages and calendar event integration**

Created comprehensive implementation plans for OpenEvent platform integration with two approaches:

1. **Approach 1: Pseudolinks** (Original plan)
   - Designed pseudolink structure with parameter passing (date, room, capacity)
   - Links to be added before existing detailed messages in agent replies
   - Easily replaceable with real platform URLs when ready

2. **Approach 2: Test Pages** (Enhanced plan - RECOMMENDED)
   - Create actual test pages to display room availability, catering menus, and Q&A
   - Build frontend pages that show raw data tables and detailed information
   - LLM verbalizer summarizes and reasons about this data in chat
   - Provides complete user experience for testing before platform integration

3. **Calendar Event Creation** (Both approaches)
   - Calendar events to be created when event reaches Lead status (Step 1)
   - Events updated when date confirmed (Step 2)
   - Status transitions tracked: Lead → Option → Confirmed

**New Documentation:**
- `implementation_plans/pseudolinks_calendar_integration.md` — Original pseudolinks approach
- `implementation_plans/test_pages_and_links_integration.md` — Enhanced test pages approach (recommended)

**Key Architecture (Test Pages Approach):**
- Chat messages show LLM reasoning and summaries (via verbalizer)
- Links lead to test pages with complete raw data
- Clear separation: reasoning (chat) vs. raw data (pages)
- Users get both concise summaries and detailed information

**Proposed Implementation:**
- Frontend pages: `/info/rooms`, `/info/catering/[menu]`, `/info/qna`
- Backend endpoints: `/api/test-data/rooms`, `/api/test-data/catering`, `/api/test-data/qna`
- Link generator: `backend/utils/pseudolinks.py` (generates real test page URLs)
- Calendar manager: `backend/utils/calendar_events.py`

**Benefits of Test Pages Approach:**
- Complete end-to-end testing of user experience
- Validates verbalizer properly summarizes complex data
- Working links improve testing and demos
- Easy migration to production platform

---

## 2025-11-27

### Safety Sandwich LLM Verbalizer

**New Feature: LLM-powered verbalization with fact verification**

The Safety Sandwich pattern enables warm, empathetic responses while guaranteeing hard facts (dates, prices, room names) are never altered or invented.

**Architecture:**
1. Deterministic engine builds `RoomOfferFacts` bundle (transient, not persisted)
2. LLM rewrites for tone while preserving facts
3. Deterministic verifier checks all facts present, none invented
4. On failure, falls back to deterministic template

**New Files:**
- `backend/ux/verbalizer_payloads.py` — Facts bundle types (RoomFact, MenuFact, RoomOfferFacts)
- `backend/ux/verbalizer_safety.py` — Verifier (extract_hard_facts, verify_output)
- `backend/ux/safety_sandwich_wiring.py` — Workflow integration helpers
- `backend/tests/verbalizer/test_safety_sandwich_room_offer.py` — 19 tests
- `backend/tests/verbalizer/test_safety_sandwich_wiring.py` — 10 tests

**Modified Files:**
- `backend/llm/verbalizer_agent.py` — Added `verbalize_room_offer()` entry point
- `backend/workflows/groups/room_availability/trigger/process.py:412-421` — Wired Safety Sandwich
- `backend/workflows/groups/offer/trigger/process.py:280-290` — Wired Safety Sandwich

**Test Results:** 29 Safety Sandwich tests pass, 161 detection/flow tests still pass

**Tone Control:**
```bash
VERBALIZER_TONE=empathetic # Human-like UX (NEW DEFAULT)
VERBALIZER_TONE=plain      # Deterministic only (for CI/testing)
```

### Universal Verbalizer (Human-Like UX)

**Enhancement: All client messages now go through the Universal Verbalizer**

The verbalization system was extended to transform ALL client-facing messages into warm, human-like communication:

**New Files:**
- `backend/ux/universal_verbalizer.py` — Core verbalizer with step-aware UX prompts
- `backend/tests/verbalizer/test_universal_verbalizer.py` — 19 tests

**Modified Files:**
- `backend/workflows/common/prompts.py` — Added `verbalize_draft_body()`, updated `append_footer()` with auto-verbalization

**Design Principles:**
1. Sound like a helpful human (conversational, not robotic)
2. Help clients decide (highlight recommendations with reasons)
3. Complete & correct (all facts preserved)
4. Show empathy (acknowledge needs)
5. Guide next steps clearly

**Test Results:** 209 tests pass (48 verbalizer tests + 161 detection/flow tests)

---

### Agent Tools Parity Tests

**New Test Module: `backend/tests/agents/`**
- Added `test_agent_tools_parity.py` — 25 tests validating tool allowlist enforcement, schema validation, and scenario parity
- Added `test_manager_approve_path.py` — 11 tests for HIL approval/rejection flows

**Test Coverage:**
- `PARITY_TOOL_001`: Tool allowlist enforced per step (Steps 2, 3, 4, 5, 7)
- `PARITY_TOOL_002`: Schema validation for required fields and formats
- `PARITY_TOOL_003`: Step policy consistency and idempotency
- `PARITY_SCENARIO_A`: Happy path Steps 1-4 tool execution
- `PARITY_SCENARIO_B`: Q&A tool triggering by step
- `PARITY_SCENARIO_C`: Detour scenario (requirements change)
- `APPROVE_HIL_001-004`: Manager approval/rejection flows

**Key Files:**
- `backend/agents/chatkit_runner.py` — Contains `ENGINE_TOOL_ALLOWLIST`, `TOOL_DEFINITIONS`, `execute_tool_call`
- `backend/agents/tools/` — Tool implementations (dates, rooms, offer, negotiation, transition, confirmation)

---

### Detection Logic Fixes

**Manager Request Detection — "real person" variant**
- Adjusted `_looks_like_manager_request` to capture "real person" variants (e.g., "I'd like to speak with a real person")
- Added regex pattern: `r"\b(speak|talk|chat)\s+(to|with)\s+(a\s+)?real\s+person\b"`
- File: `backend/llm/intent_classifier.py:229`
- Test: `test_DET_MGR_002_real_person` in `backend/tests/detection/test_manager_request.py`

**Parking Q&A Detection**
- Aligned parking Q&A detection with canonical `parking_policy` type
- Added keywords `" park"` (with leading space to avoid false positives) and `"park?"` to match "where can guests park?"
- File: `backend/llm/intent_classifier.py:157-158`
- Test: `test_DET_QNA_006_parking_question` in `backend/tests/detection/test_qna_detection.py`

### Test Results

All 161 detection and flow tests pass:
- `backend/tests/detection/` — 120 tests
- `backend/tests/flow/` — 19 tests
- `backend/tests/regression/` — 22 tests

---

## Prior Changes

See `docs/TEAM_GUIDE.md` for historical bug fixes and their corresponding tests.
