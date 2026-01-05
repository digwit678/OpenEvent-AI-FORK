# Open Items Plan (03.01.26)

## Goal
Finish remaining corrections after authentication + multi-tenancy and align fallback behavior so clients never see fallbacks; OpenEvent receives all alerts.

## Plan

### 1) Consistent Fallback/Manual-Review Suppression
- Make `start_conversation` suppress manual review replies (currently returns a client message).
- Centralize suppression so every fallback returns empty client response in production.
- Files: `backend/api/routes/messages.py`, `backend/core/fallback.py`

### 2) Guarantee OpenEvent Alerting in Production
- Remove hard-coded default recipients or require explicit config.
- Add startup check: if `ENV=prod` and alerting is not configured, log critical and disable suppression (or exit).
- Files: `backend/services/error_alerting.py`, `backend/core/fallback.py`, `backend/api/routes/config.py`

### 3) Hard Override for Fallback Suppression
- Add `SUPPRESS_CLIENT_FALLBACKS=1` to force suppression regardless of `ENV`.
- Files: `backend/core/fallback.py`

### 4) Harden JSON Multi-Tenancy Headers
- Validate `X-Team-Id` format before using it in JSON file paths.
- Only accept tenant headers when `TENANT_HEADER_ENABLED=1` and not prod.
- Files: `backend/api/middleware/tenant_context.py`, `backend/workflow_email.py`

### 5) Manager-Level Isolation (If Required)
- Decide whether isolation is per-team or per-manager.
- If per-manager is required, implement per-manager JSON files or add `manager_id` filtering.
- Files: `backend/workflow_email.py`, `backend/workflows/io/database.py`

### 6) Tighten Auth Allowlist
- Remove `/api/qna` from public allowlist or guard it by env.
- Files: `backend/api/middleware/auth.py`

### 7) Dual-LLM Verification Robustness
- Ensure verifier uses a different provider than the generator.
- If same provider, log that verification is not independent.
- Files: `backend/ux/universal_verbalizer.py`, `backend/llm/provider_config.py`

### 8) Production Env Checklist (Non-Code)
- `ENV=prod`, `AUTH_ENABLED=1`, `RATE_LIMIT_ENABLED=1`, `TENANT_HEADER_ENABLED=0`
- Configure error alerting recipients (OpenEvent emails) + SMTP.
- Smoke test: trigger fallback and confirm **no client message + alert email sent**.
