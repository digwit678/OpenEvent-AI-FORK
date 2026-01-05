# Open Items Plan (03.01.26)

## Goal
Finish remaining corrections after authentication + multi-tenancy and align fallback behavior so clients never see fallbacks; OpenEvent receives all alerts.

## Status Summary
| # | Item | Status |
|---|------|--------|
| 1 | Fallback Suppression | DONE |
| 2 | OpenEvent Alerting | DONE |
| 3 | Hard Override | DONE |
| 4 | JSON Multi-Tenancy Headers | DONE |
| 5 | Manager-Level Isolation | DONE |
| 6 | Tighten Auth Allowlist | DONE |
| 7 | Dual-LLM Verification | DONE |
| 8 | Production Env Checklist | N/A (non-code) |

## Plan

### 1) Consistent Fallback/Manual-Review Suppression - DONE
- Make `start_conversation` suppress manual review replies (currently returns a client message).
- Centralize suppression so every fallback returns empty client response in production.
- Files: `backend/api/routes/messages.py`, `backend/core/fallback.py`

### 2) Guarantee OpenEvent Alerting in Production - DONE
- Remove hard-coded default recipients or require explicit config.
- Add startup check: if `ENV=prod` and alerting is not configured, log critical and disable suppression (or exit).
- Files: `backend/services/error_alerting.py`, `backend/core/fallback.py`, `backend/api/routes/config.py`

### 3) Hard Override for Fallback Suppression - DONE
- Add `SUPPRESS_CLIENT_FALLBACKS=1` to force suppression regardless of `ENV`.
- Files: `backend/core/fallback.py`

### 4) Harden JSON Multi-Tenancy Headers - DONE
- Validate `X-Team-Id` format before using it in JSON file paths.
- Only accept tenant headers when `TENANT_HEADER_ENABLED=1` and not prod.
- Files: `backend/api/middleware/tenant_context.py`, `backend/workflow_email.py`

### 5) Manager-Level Isolation - DONE (05.01.26)
- **Decision**: Per-manager isolation (each user sees only their own events)
- **Implementation**: File-level isolation using `events_{manager_id}.json`
- **Changes**:
  - Added `get_manager_id()` helper in `backend/workflows/io/integration/config.py`
  - Store `manager_id` in `create_event_entry()` at `backend/workflows/io/database.py`
  - Updated `_resolve_tenant_db_path()` to prioritize `manager_id` over `team_id`
  - Updated `_resolve_db_path()` in adapter for consistency
- **Routing priority**: `X-Manager-Id` > `X-Team-Id` > default file

### 6) Tighten Auth Allowlist - DONE
- Remove `/api/qna` from public allowlist or guard it by env.
- Files: `backend/api/middleware/auth.py`

### 7) Dual-LLM Verification Robustness - DONE
- Ensure verifier uses a different provider than the generator.
- If same provider, log that verification is not independent.
- Files: `backend/ux/universal_verbalizer.py`, `backend/llm/provider_config.py`

### 8) Production Env Checklist (Non-Code)
- `ENV=prod`, `AUTH_ENABLED=1`, `RATE_LIMIT_ENABLED=1`, `TENANT_HEADER_ENABLED=0`
- Configure error alerting recipients (OpenEvent emails) + SMTP.
- Smoke test: trigger fallback and confirm **no client message + alert email sent**.
