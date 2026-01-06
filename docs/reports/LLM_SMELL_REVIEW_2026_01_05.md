# LLM Smell Review - 2026-01-05

## Scope

- Repository: OpenEvent-AI (production backend only; frontend excluded)
- Focus: LLM smells, hardcoded NLP, overly specific solutions, gatekeeping risks, security weaknesses
- Excluded: docs/reports/OPEN_ITEMS_PLAN_2026_01_03.md

## Findings

### High

- Rate limiting is referenced in `backend/main.py` but the middleware module is missing from the repo; this breaks startup or leaves production without rate limits. Reference: `backend/main.py:46`
- LLM sanitization utilities exist but are not applied at core LLM entrypoints; raw message content and event state are embedded in prompts/JSON, increasing prompt injection and data exposure risk. References: `backend/workflows/llm/sanitize.py:1`, `backend/detection/unified.py:222`, `backend/detection/qna/general_qna.py:358`, `backend/workflows/qna/extraction.py:206`, `backend/ux/universal_verbalizer.py:776`
- Authentication is disabled by default; if AUTH_ENABLED is not explicitly set in production, all API endpoints (including config/prompt edits) are publicly writable. References: `backend/api/middleware/auth.py:8`, `backend/api/routes/config.py:1`
- Production safety depends on ENV being set; default ENV is dev, which mounts debug/test routers and enables debug tracing when ENV is misconfigured in production. References: `backend/main.py:50`, `backend/main.py:149`, `backend/debug/settings.py:5`

### Medium

- Hardcoded room IDs and ordering are scattered across the Q&A and room pipelines, making behavior brittle for venues with different inventory. References: `backend/workflows/common/general_qna.py:29`, `backend/workflows/qna/router.py:42`, `backend/workflows/steps/step3_room_availability/trigger/constants.py:15`, `backend/workflows/common/room_rules.py:11`
- Out-of-context intent gating returns no response; misclassification can silently drop valid user actions. References: `backend/workflows/runtime/pre_route.py:37`, `backend/workflows/runtime/pre_route.py:154`
- Pre-filter defaults to legacy mode despite comments claiming enhanced default; skip flags can bypass LLM on short confirmations, risking missed intent/entity changes. References: `backend/detection/pre_filter.py:10`, `backend/detection/pre_filter.py:349`
- Heuristic intent override can force EVENT_REQUEST based on token lists + counts, potentially misrouting pricing/Q&A queries into booking flow. References: `backend/workflows/llm/adapter.py:725`, `backend/workflows/llm/adapter.py:791`
- Language-specific heuristics are mostly EN/DE lists, which will miss other languages and phrasing variations. References: `backend/detection/qna/general_qna.py:46`, `backend/detection/pre_filter.py:101`, `backend/workflows/steps/step1_intake/trigger/confirmation_parsing.py:17`
- Auth allowlist includes `/` and `/api/workflow/health`, which return event counts and absolute DB path even when auth is enabled (information leak). References: `backend/api/middleware/auth.py:34`, `backend/main.py:452`, `backend/api/routes/workflow.py:20`
- Tenant header overrides are accepted when TENANT_HEADER_ENABLED=1; if enabled in production or auth is off, headers can steer tenant context (misconfig risk). Reference: `backend/api/middleware/tenant_context.py:46`
- LLM analysis cache is unbounded and retains message content in memory for the lifetime of the process, risking memory growth and PII retention. Reference: `backend/workflows/llm/adapter.py:247`
- Snapshot storage writes to a shared JSON file without file locking; concurrent requests can corrupt snapshots in multi-worker deployments. Reference: `backend/utils/page_snapshots.py:40`
- Deposit payment endpoint is documented as a mock for testing; it should be gated/disabled in production or tightly controlled. Reference: `backend/api/routes/events.py:41`

### Low

- Unified detection prompt assumes current year for yearless dates, which can mis-handle multi-year planning. Reference: `backend/detection/unified.py:186`
- Error alerting emails include full client message content; ensure alert recipients are trusted to avoid PII leakage. Reference: `backend/services/error_alerting.py:90`

## Open Questions

- Is silent ignore for out-of-context intents intentional in production, or should it reply with a clarifying prompt?
- Should Room A/B/C/Punkt.Null remain defaults, or should room metadata be sourced exclusively from config/data?
- Should LLM entrypoints consistently sanitize message payloads before prompt assembly?
- Should public allowlist endpoints (`/`, `/api/workflow/health`) be gated in production?
- Should mock endpoints (deposit pay, test data) be disabled or compiled out in production builds?