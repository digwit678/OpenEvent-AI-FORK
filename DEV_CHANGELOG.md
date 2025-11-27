# Development Changelog

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
VERBALIZER_TONE=plain      # Deterministic only (default)
VERBALIZER_TONE=empathetic # LLM verbalization enabled
```

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
