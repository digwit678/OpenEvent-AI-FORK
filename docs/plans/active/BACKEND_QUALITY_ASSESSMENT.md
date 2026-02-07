
# Backend Quality Assessment

> **Date:** 2026-02-06
> **Branch:** `development-branch`
> **Method:** 5-agent parallel review (code review, silent-failure hunt, code simplification, comment analysis, type design)

---

## Overall RAG Summary

| Area | Rating | Notes |
|------|--------|-------|
| **Security** | RED | Auth opt-in (not opt-out), unprotected GETs, JWT stub |
| **Code Quality** | GREEN | God functions refactored (CQ-2/3), stray print fixed (CQ-1), duplication resolved (CQ-4) |
| **Resilience** | AMBER | Good fallbacks; no circuit breaker for LLM calls |
| **Architecture** | GREEN | Solid layered design, defensive programming throughout |
| **Maintainability** | GREEN | Excellent docs (TEAM_GUIDE 895 lines, 51 bugs tracked) |
| **Testing** | AMBER | Strong detection suite (~460 tests); API/adapter gaps |

---

## Action Items — Checkbox Tracker

### Critical (Before any prod traffic) — Deferred to production branch

> Security items are tracked in `docs/integration/supabase/TODO_STEPS.md` § 5. 
> They apply at integration time, not on the dev/testing branch.

- [ ] **SEC-1** — Make auth opt-out, not opt-in *(deferred → integration)*
- [ ] **SEC-2** — Add `@require_auth` to unprotected GET routes *(deferred → integration)*
- [ ] **SEC-3** — Implement real Supabase JWT verification *(deferred → integration)*
- [x] **CQ-1** — Remove stray `print()` from `pre_route.py:257`
  - Done this session — `logger.debug()` on lines 258-262 covers the same data
- [x] **TEST-1** — Delete duplicate test directories (`test_agents/`, `test_api/`, `test_detection/`)
  - Done this session — moved unique file `test_middleware_reliability.py` to `tests/api/` first

### High (Before MVP — ~1 week)

- [x] **CQ-2** — Refactor god function in `step1_handler.py` (836 → 525 lines, 37% reduction)
  - Extracted: `early_pipeline.py`, `change_pipeline.py`; extended `manual_review_gate.py`, `room_shortcut.py`
- [x] **CQ-3** — Refactor god function in `step4_handler.py` (1190 → 301 lines, 75% reduction)
  - Extracted: `helpers.py`, `confirmation_continuation.py`, `change_routing_step4.py`, `acceptance.py`; extended `compose.py`
- [x] **CQ-4** — Eliminate verbalizer duplication (~200 lines shared between `llm/verbalizer_agent.py` and `ux/universal_verbalizer.py`)
  - Consolidated into single source of truth (commit `ed1826b`)
- [ ] **TEST-2** — Add API route tests (12+ routes have zero test coverage)
  - Priority: auth middleware, events CRUD, config endpoints
- [ ] **TEST-3** — Add LLM adapter tests (`llm/adapters/` directory untested)
- [ ] **RES-1** — Implement circuit breaker for LLM API failures
  - Currently retries indefinitely; need backoff + fallback after N failures

### Medium (Refactoring — 2-3 weeks)

- [ ] **CQ-5** — Replace magic status strings with `EventStatus` enum
  - Strings like `"pending"`, `"confirmed"`, `"cancelled"` scattered across codebase
- [ ] **CQ-6** — Simplify complex nested conditionals in routing logic
  - `pre_route.py` and step handlers have 4-5 level deep nesting
- [ ] **ARCH-1** — Delete legacy session store (unused since Supabase migration)
- [ ] **ARCH-2** — Reorganize `workflows/common/` into focused submodules
  - Currently a flat bag of utilities; split by domain (pricing, scheduling, cancellation)

### Low (Nice-to-have)

- [ ] **OPS-1** — Set up systemd user task for backend process management
  - Deferred — requires production environment access
- [ ] **DOC-1** — Add architecture decision records (ADRs) for key design choices
- [ ] **CQ-7** — Add type annotations to untyped public functions in `workflows/io/`

---

## Detailed Findings

### 1. Security (RED)

**SEC-1: Auth is opt-in, not opt-out**
- File: `api/middleware/auth.py`
- The auth middleware only activates when `AUTH_ENABLED=1` is explicitly set. If an operator deploys without this env var, all endpoints are unprotected. Production systems should default to secure.

**SEC-2: Unprotected GET endpoints**
- Files: `api/routes/events.py`, `api/routes/config.py`, `api/routes/messages.py`
- Several GET endpoints return full event data, configuration, and message history without any authentication check. Even read-only endpoints need auth in a multi-tenant system.

**SEC-3: JWT verification stub**
- File: `api/middleware/auth.py` — `verify_team_membership()`
- Team membership verification is stubbed (always returns True). This means any valid JWT can access any tenant's data.

### 2. Code Quality (AMBER)

**CQ-1: Stray print() in production path** [FIXED]
- File: `workflows/runtime/pre_route.py:257`
- A `print(f"[UNIFIED_DETECTION] ...")` was left in the hot path. The adjacent `logger.debug()` already logs the same fields with proper formatting.

**CQ-2/CQ-3: God functions in step handlers** [FIXED]
- `step1_handler.py` reduced from 836 → 525 lines (37%). Extracted: `early_pipeline.py` (early detection chain), `change_pipeline.py` (change routing); extended `manual_review_gate.py`, `room_shortcut.py`.
- `step4_handler.py` reduced from 1190 → 301 lines (75%). Extracted: `helpers.py` (internal utilities), `confirmation_continuation.py` (BUG-053 gate), `change_routing_step4.py` (change detection + Q&A + nonsense), `acceptance.py` (offer acceptance flow); extended `compose.py` (offer finalization pipeline).
- Both handlers are now thin orchestrators (~250 LOC each) calling focused modules. 268 tests pass, E2E verified through Step 7.

**CQ-4: Verbalizer duplication**
- `llm/verbalizer_agent.py` and `ux/universal_verbalizer.py` share ~200 lines of near-identical response formatting logic. Changes to one are often forgotten in the other.

### 3. Resilience (AMBER)

**RES-1: No circuit breaker for LLM calls**
- LLM adapters retry on failure but have no circuit breaker. If OpenAI/Gemini is down, every request will hang on retries before timing out. A circuit breaker would fail fast after N consecutive failures and periodically probe for recovery.

**Strengths:** The codebase has good defensive patterns — `.get()` for dict access, fallback responses when LLM calls fail, and structured error logging throughout.

### 4. Architecture (GREEN)

The layered architecture is solid:
- Clear separation: `api/` → `workflows/runtime/` → `workflows/steps/` → `workflows/io/`
- Detection pipeline is well-factored: `detection/unified.py` as single entry point
- State management follows documented patterns (TEAM_GUIDE)

### 5. Maintainability (GREEN)

- TEAM_GUIDE.md (895 lines) is comprehensive with 51 documented bug fixes
- DEV_CHANGELOG.md tracks all changes
- CLAUDE.md provides clear agent guidance
- Test matrix (`tests/TEST_MATRIX_detection_and_flow.md`) maps tests to features

### 6. Testing (AMBER)

**Strong areas (~460 tests):**
- Detection: acceptance, cancellation, change requests, Q&A, hybrid messages
- Regression: workflow flows, step transitions, edge cases
- Unit: pricing, country/timezone, response style

**Gaps:** [PARTIALLY FIXED]
- API routes: 12+ routes with zero test coverage
- LLM adapters: no unit tests for adapter layer
- Duplicate test directories caused ~25 collection errors [FIXED this session]

---

## Production Readiness Estimate

| Milestone | Effort | Items |
|-----------|--------|-------|
| **Secure for staging** | 1-2 days | SEC-1, SEC-2, SEC-3 |
| **MVP quality bar** | ~1 week | + TEST-2, RES-1 (CQ-2/3 done) |
| **Full production** | 3-4 weeks | + all Medium/Low items |

---

*Report generated by 5-agent parallel review. Quick wins (CQ-1, TEST-1) applied on `development-branch` same session.*
