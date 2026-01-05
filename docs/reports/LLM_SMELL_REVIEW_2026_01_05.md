# LLM Smell Review - 2026-01-05

## Scope

- Repository: OpenEvent-AI (production backend only; frontend excluded)
- Focus: LLM smells, hardcoded NLP, overly specific solutions, gatekeeping risks, security weaknesses
- Excluded: docs/reports/OPEN_ITEMS_PLAN_2026_01_03.md

---

## Status Summary

| Severity | Total | Resolved | Pending |
|----------|-------|----------|---------|
| HIGH | 3 | 1 | 2 |
| MEDIUM | 7 | 5 | 2 |
| LOW | 2 | 0 | 2 |

---

## Findings

### High

- ✅ **RESOLVED** (2026-01-05): LLM sanitization utilities exist but are not applied at core LLM entrypoints; raw message content and event state are embedded in prompts/JSON, increasing prompt injection and data exposure risk.
  - **Fix**: Applied `sanitize_for_llm()` at `unified.py`, `extraction.py`, `adapter.py`
  - References: `backend/workflows/llm/sanitize.py:1`, `backend/detection/unified.py:222`

- ⚠️ **PENDING**: Authentication is disabled by default; if AUTH_ENABLED is not explicitly set in production, all API endpoints (including config/prompt edits) are publicly writable.
  - **Status**: Tracked in OPEN_ITEMS_PLAN - requires production deployment config
  - References: `backend/api/middleware/auth.py:8`, `backend/api/routes/config.py:1`

- ⚠️ **PENDING**: Production safety depends on ENV being set; default ENV is dev, which mounts debug/test routers and dev-only behavior if ENV is misconfigured in production.
  - **Status**: Tracked in OPEN_ITEMS_PLAN - requires production deployment config
  - References: `backend/main.py:50`, `backend/main.py:149`

### Medium

- ✅ **RESOLVED** (2026-01-05): Hardcoded room IDs and ordering are scattered across the Q&A and room pipelines, making behavior brittle for venues with different inventory.
  - **Fix**: All room data now loaded from `backend/data/rooms.json`. Functions: `load_rooms()`, `get_room_ids()`, `get_room_size_order()`, `get_room_aliases()`
  - References: `backend/workflows/common/general_qna.py`, `backend/workflows/qna/router.py`, `backend/workflows/steps/step3_room_availability/trigger/constants.py`, `backend/workflows/common/room_rules.py`

- ✅ **RESOLVED** (2026-01-05): Out-of-context intent gating returns no response; misclassification can silently drop valid user actions.
  - **Decision**: Keep silent drop behavior. These cases are rare, and the next client message usually gets things back on track.
  - References: `backend/workflows/runtime/pre_route.py:37`

- ✅ **RESOLVED** (2026-01-05): Pre-filter defaults to legacy mode despite comments claiming enhanced default; skip flags can bypass LLM on short confirmations, risking missed intent/entity changes.
  - **Fix**: Changed default from "legacy" to "enhanced" in `get_pre_filter_mode()`
  - References: `backend/detection/pre_filter.py:27`

- ✅ **RESOLVED** (2026-01-05): Heuristic intent override can force EVENT_REQUEST based on token lists + counts, potentially misrouting pricing/Q&A queries into booking flow.
  - **Fix**: Override now explicitly excludes `GENERAL_QNA` - never overrides Q&A intent. Only rescues when LLM returns garbage ("other", "non_event").
  - References: `backend/workflows/llm/adapter.py:828`

- ✅ **RESOLVED** (2026-01-05): Language-specific heuristics are mostly EN/DE lists, which will miss other languages and phrasing variations.
  - **Fix**: Added French keywords for Lausanne client (dîner, réunion, personnes, etc.)
  - References: `backend/workflows/llm/adapter.py:762`

- ⚠️ **PENDING**: Auth allowlist includes `/` and `/api/workflow/health`, which return event counts and absolute DB path even when auth is enabled (information leak).
  - **Risk**: Low - operational info, not user data
  - References: `backend/api/middleware/auth.py:34`, `backend/main.py:452`

- ✅ **RESOLVED** (OPEN_ITEMS_PLAN): Tenant header overrides are accepted when TENANT_HEADER_ENABLED=1; if enabled in production or auth is off, headers can steer tenant context (misconfig risk).
  - **Fix**: Headers validated for format, TENANT_HEADER_ENABLED=0 enforced in prod
  - Reference: `backend/api/middleware/tenant_context.py`

### Low

- ⚪ **DEFERRED**: Unified detection prompt assumes current year for yearless dates, which can mis-handle multi-year planning.
  - **Risk**: Edge case - only affects bookings 12+ months ahead
  - Reference: `backend/detection/unified.py:186`

- ⚪ **DEFERRED**: Error alerting emails include full client message content; ensure alert recipients are trusted to avoid PII leakage.
  - **Risk**: Operational - recipients are internal OpenEvent staff
  - Reference: `backend/services/error_alerting.py:90`

---

## Open Questions - Resolved

| Question | Decision |
|----------|----------|
| Is silent ignore for out-of-context intents intentional? | Yes, keep silent |
| Should room metadata be sourced from config only? | Yes, now from `rooms.json` |
| Should LLM entrypoints sanitize payloads? | Yes, now implemented |
| Should public allowlist endpoints be gated in production? | Low priority, operational info only |

---

## Still Pending

1. **AUTH_ENABLED default** - Must be explicitly set in production deployment
2. **ENV default** - Must be explicitly set to "prod" in production deployment
3. **Health endpoint info leak** - Consider removing DB path from response
4. **Year assumption** - Low priority edge case
5. **Error alerting PII** - Operational concern, recipients are trusted
