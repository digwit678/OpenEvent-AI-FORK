# Production Readiness Findings

## Executive Summary
- Overall risk rating: Blocker
- Top findings (titles only):
  - systemd unit references missing backend.main entrypoint
  - Authentication disabled by default for all API routes
  - ENV defaults to dev, enabling debug/test endpoints and dev behaviors
  - VPS setup script installs a non-existent requirements file
  - Primary data store is a local JSON file on disk
  - Committed events_database.json contains populated event data
  - In-memory conversation state store loses data on restart
  - Runtime dependencies are not pinned
  - systemd service runs as root
  - Rate limit toggle is documented but not implemented in code

## Coverage
### Inspected
- .github/workflows (agent-canary.yml, ci-smoke.yml, sdk-probe.yml, workflow-tests.yml, legacy/*)
- api (middleware, routes)
- core (fallback)
- debug
- deploy (systemd unit, setup script, nginx config, README)
- legacy (session_store)
- workflow_email.py, main.py, config.py, vercel.json
- requirements.txt, requirements-dev.txt
- events_database.json

### Commands Executed
- `ls` — listed repo root
- `ls -a` — listed hidden entries
- `ls backend` — showed only events_database.json and tmp-cache
- `find backend -maxdepth 2 -type f` — confirmed no backend/main.py present
- `rg -n "print\\(" backend` — no matches (rg exit 1)
- `rg -n "except Exception\\s*:\\s*(pass)?$" backend` — no matches (rg exit 1)
- `rg -n "OE_FALLBACK_DIAGNOSTICS|FALLBACK" backend` — no matches (rg exit 1)
- `rg -n "ENABLE_DANGEROUS_ENDPOINTS" backend` — no matches (rg exit 1)
- `ls .github` — listed workflows directory
- `ls .github/workflows` — listed active workflows
- `ls .github/workflows/legacy` — listed legacy workflows
- `rg -n "FastAPI|uvicorn|flask|starlette"` — located FastAPI references across repo
- `rg -n "traceback\\.format_exc"` — found usage in api/routes/test_data.py
- `rg -n "ENABLE_DANGEROUS_ENDPOINTS"` — found usages in api/routes/clients.py and docs
- `rg --files -g "backend/main.py"` — no results
- `rg --files -g "package.json"` — no results
- `rg -n "AUTH_MODE|AUTH_ENABLED"` — found usages in auth middleware and docs
- `rg -n "RATE_LIMIT"` — found only in docs
- `rg -n "AUTO_FREE_BACKEND_PORT|AUTO_LAUNCH_FRONTEND|AUTO_OPEN_FRONTEND" main.py` — located dev-only defaults
- `rg -n "router = APIRouter|@router.post\\(\\\"/global-deposit\\\"" api/routes/config.py` — confirmed config write endpoints
- `rg -n "app = FastAPI" main.py` — located FastAPI app definition
- `rg -n "email" events_database.json | head -n 5` — found email fields
- `rg -n "@" events_database.json | head -n 5` — found example email addresses
- `rg -n "\\\"Phone\\\"" events_database.json | head -n 5` — found phone fields
- `rg -n "active_conversations" api/routes/messages.py | head -n 5` — found in-memory session usage
- `ls requirements-dev*` — confirmed only requirements-dev.txt exists
- `git branch --show-current` — feature/prelaunch-fixes-with-frontend-jan-2026
- `nl -ba deploy/openevent.service` — inspected systemd unit
- `nl -ba deploy/setup-vps.sh | sed -n '38,120p'` — inspected setup script install steps
- `nl -ba main.py | sed -n '30,80p'` — inspected ENV default and router setup
- `nl -ba main.py | sed -n '118,150p'` — inspected FastAPI app and router inclusion
- `nl -ba main.py | sed -n '150,190p'` — inspected middleware and CORS defaults
- `nl -ba main.py | sed -n '252,280p'` — inspected auto-kill port logic
- `nl -ba debug/settings.py` — inspected debug trace defaults
- `nl -ba api/middleware/auth.py | sed -n '1,120p'` — inspected auth defaults
- `nl -ba api/middleware/auth.py | sed -n '140,220p'` — inspected auth enable/disable logic
- `nl -ba api/routes/config.py | sed -n '180,220p'` — inspected config write endpoints
- `nl -ba api/routes/debug.py | sed -n '1,120p'` — inspected debug endpoints
- `nl -ba api/routes/test_data.py | sed -n '160,220p'` — inspected traceback return
- `nl -ba api/routes/messages.py | sed -n '24,40p'` — inspected session store usage
- `nl -ba workflow_email.py | sed -n '210,235p'` — inspected DB_PATH selection
- `nl -ba legacy/session_store.py | sed -n '30,90p'` — inspected in-memory storage
- `nl -ba events_database.json | sed -n '1,70p'` — inspected committed data sample
- `nl -ba requirements.txt` — inspected dependency pinning

## Findings Index
| ID | Severity | Area | Title | Location | Confidence | Verified? |
|---|---|---|---|---|---|---|
| PR-001 | Blocker | CI-CD | systemd unit references missing backend.main entrypoint | `deploy/openevent.service:11`<br>`main.py:127` | High | Yes |
| PR-002 | High | CI-CD | VPS setup script installs non-existent requirements file | `deploy/setup-vps.sh:53`<br>`requirements-dev.txt:1` | High | Yes |
| PR-003 | Critical | Security | Authentication disabled by default for all API routes | `api/middleware/auth.py:8`<br>`api/middleware/auth.py:150`<br>`main.py:160`<br>`api/routes/config.py:193` | High | Yes |
| PR-004 | High | Security | ENV defaults to dev, enabling debug/test endpoints and dev behaviors | `main.py:52`<br>`main.py:135`<br>`debug/settings.py:8`<br>`api/routes/debug.py:5`<br>`api/routes/test_data.py:175` | High | Yes |
| PR-005 | High | Reliability | Primary data store is a local JSON file on disk | `workflow_email.py:219` | High | Yes |
| PR-006 | Medium | Compliance | Committed events_database.json contains populated event data | `events_database.json:1` | High | Yes |
| PR-007 | Medium | Reliability | In-memory conversation state store loses data on restart | `legacy/session_store.py:36`<br>`api/routes/messages.py:30` | High | Yes |
| PR-008 | Medium | Dependencies | Runtime dependencies are not pinned | `requirements.txt:5` | High | Yes |
| PR-009 | Medium | Security | systemd service runs as root | `deploy/openevent.service:6` | High | Yes |
| PR-010 | Medium | Security | Rate limit toggle is documented but not implemented in code | `deploy/README.md:148` | Medium | Yes |

## Detailed Findings

## PR-001 systemd unit references missing backend.main entrypoint
- Severity: Blocker
- Confidence: High
- Area: CI-CD
- Evidence:
  - `deploy/openevent.service:11`
    ```ini
    ExecStart=/opt/openevent/venv/bin/uvicorn backend.main:app --host 0.0.0.0 --port 8000
    ```
  - `main.py:127`
    ```py
    app = FastAPI(title="AI Event Manager", lifespan=lifespan)
    ```
  - Command output:
    ```
    rg --files -g "backend/main.py"
    (no results)
    ```
- Impact:
  - Service startup fails at import time if the systemd unit is used as-is.
  - Preconditions: deployment uses `deploy/openevent.service` and relies on `backend.main:app`.
- Notes:
  - Assumption: the repo is deployed as-is without an additional packaging step that creates a `backend` module.
  - Open question: Is there a build artifact or separate repo that provides `backend/main.py`?

## PR-002 VPS setup script installs non-existent requirements file
- Severity: High
- Confidence: High
- Area: CI-CD
- Evidence:
  - `deploy/setup-vps.sh:53`
    ```bash
    ./venv/bin/pip install -r requirements-dev
    ```
  - Command output:
    ```
    ls requirements-dev*
    requirements-dev.txt
    ```
- Impact:
  - Dependency installation fails under `set -e`, stopping the VPS setup script before the service is enabled.
  - Preconditions: running `deploy/setup-vps.sh` as provided.
- Notes:
  - Assumption: the repository is used without additional files outside the repo root.
  - Open question: Is there a packaging step that generates a `requirements-dev` file outside version control?

## PR-003 Authentication disabled by default for all API routes
- Severity: Critical
- Confidence: High
- Area: Security
- Evidence:
  - `api/middleware/auth.py:8`
    ```py
    Default: AUTH_ENABLED=0 (no auth checks - dev/test behavior unchanged)
    ```
  - `api/middleware/auth.py:150`
    ```py
    if os.getenv("AUTH_ENABLED", "0") != "1":
        return await call_next(request)
    ```
  - `main.py:160`
    ```py
    app.add_middleware(AuthMiddleware)
    ```
  - `api/routes/config.py:193`
    ```py
    @router.post("/global-deposit")
    async def set_global_deposit_config(config: GlobalDepositConfig):
    ```
- Impact:
  - If `AUTH_ENABLED` is unset or set to `0`, all endpoints, including write endpoints under `/api/config`, are publicly accessible.
  - Preconditions: deployment without `AUTH_ENABLED=1` (or equivalent external access control).
- Notes:
  - Assumption: no upstream gateway or network policy restricts access to the API.
  - Open question: Is API access always restricted by infrastructure outside this repo?

## PR-004 ENV defaults to dev, enabling debug/test endpoints and dev behaviors
- Severity: High
- Confidence: High
- Area: Security
- Evidence:
  - `main.py:52`
    ```py
    _IS_DEV = os.getenv("ENV", "dev").lower() in ("dev", "development", "local")
    ```
  - `main.py:135`
    ```py
    if _IS_DEV:
        app.include_router(debug_router)
    ```
  - `debug/settings.py:8`
    ```py
    _IS_DEV = os.getenv("ENV", "dev").lower() in ("dev", "development", "local")
    ```
  - `api/routes/debug.py:5`
    ```py
    ROUTES:
        GET  /api/debug/threads/{thread_id}              - Get full trace for thread
    ```
  - `api/routes/test_data.py:175`
    ```py
    except Exception as e:
        import traceback
        return { "error": str(e), "traceback": traceback.format_exc(), "success": False }
    ```
  - `main.py:265`
    ```py
    if os.getenv("AUTO_FREE_BACKEND_PORT", "1" if _IS_DEV else "0") != "1":
    ```
- Impact:
  - Debug endpoints can expose internal traces/logs, and test endpoints can return stack traces to clients.
  - Dev-only behaviors (auto-kill port listeners, auto-launch frontend) activate when `ENV` is not explicitly set.
  - Preconditions: `ENV` unset or set to a dev value.
- Notes:
  - Assumption: production environments do not always set `ENV=prod`.
  - Open question: Are debug and test routes further constrained by upstream routing or firewall rules?

## PR-005 Primary data store is a local JSON file on disk
- Severity: High
- Confidence: High
- Area: Reliability
- Evidence:
  - `workflow_email.py:219`
    ```py
    if os.getenv("VERCEL") == "1":
        DB_PATH = Path("/tmp/events_database.json")
    else:
        DB_PATH = Path(__file__).with_name("events_database.json")
    ```
- Impact:
  - Data durability depends on a single local file; multi-instance deployments can diverge or lose data on host failure.
  - Preconditions: non-Vercel deployment using default DB_PATH.
- Notes:
  - Assumption: no external database or persistence layer is used outside this code path.
  - Open question: Is there an alternative storage backend in production not represented here?

## PR-006 Committed events_database.json contains populated event data
- Severity: Medium
- Confidence: High
- Area: Compliance
- Evidence:
  - `events_database.json:1`
    ```json
    {
      "events": [
        {
          "event_id": "62c1c118-fe5c-4d61-867e-4bfe709bb0d3",
          "event_data": {
            "Email": "e2e-test@example.com"
    ```
- Impact:
  - New deployments begin with pre-populated data; risk of data contamination and inadvertent exposure if the file is served or shipped.
  - Preconditions: default database file is deployed to production hosts or containers.
- Notes:
  - Assumption: the sample data is non-production; actual provenance of entries is unknown from the repo alone.
  - Open question: Is this file intended for testing only and excluded in production builds?

## PR-007 In-memory conversation state store loses data on restart
- Severity: Medium
- Confidence: High
- Area: Reliability
- Evidence:
  - `legacy/session_store.py:36`
    ```py
    # In-memory storage for demo
    active_conversations: dict[str, ConversationState] = {}
    ```
  - `api/routes/messages.py:30`
    ```py
    from legacy.session_store import (
        active_conversations,
    )
    ```
- Impact:
  - Conversation state disappears on process restart and does not share across multiple workers, causing lost sessions and inconsistent behavior.
  - Preconditions: server restart, crash, or multi-worker deployment.
- Notes:
  - Assumption: this in-memory store is used for live traffic (not only for local demos).
  - Open question: Is there a separate state store used in production that bypasses this path?

## PR-008 Runtime dependencies are not pinned
- Severity: Medium
- Confidence: High
- Area: Dependencies
- Evidence:
  - `requirements.txt:5`
    ```txt
    fastapi>=0.104.0
    uvicorn[standard]>=0.24.0
    pydantic[email]>=2.0.0
    ```
- Impact:
  - Builds are non-reproducible and can change over time, increasing the risk of unexpected runtime behavior.
  - Preconditions: deployments install from `requirements.txt` without lockfiles or hashes.
- Notes:
  - Assumption: no separate lockfile is used for production builds.
  - Open question: Is there a pinned lock file used by CI or deployment pipelines outside this repo?

## PR-009 systemd service runs as root
- Severity: Medium
- Confidence: High
- Area: Security
- Evidence:
  - `deploy/openevent.service:6`
    ```ini
    User=root
    ```
- Impact:
  - A compromise of the service process would grant root-level access to the host.
  - Preconditions: using the provided systemd unit.
- Notes:
  - Assumption: systemd service is used as-is in production.
  - Open question: Is the service account changed during deployment automation?

## PR-010 Rate limit toggle is documented but not implemented in code
- Severity: Medium
- Confidence: Medium
- Area: Security
- Evidence:
  - `deploy/README.md:148`
    ```md
    RATE_LIMIT_ENABLED=1          # Prevents abuse
    ```
  - Command output:
    ```
    rg -n "RATE_LIMIT"
    deploy/README.md:148:RATE_LIMIT_ENABLED=1          # Prevents abuse
    deploy/README.md:167:# Add: ENV=prod AUTH_ENABLED=1 RATE_LIMIT_ENABLED=1 TENANT_HEADER_ENABLED=0
    deploy/README.md:182:- [ ] `RATE_LIMIT_ENABLED=1` set
    deploy/README.md:195:| `RATE_LIMIT_ENABLED` | 0 | **1** | Prevents abuse |
    docs/reports/PROD_READINESS_PLAN_2026_01_07.md:65:- Make it configurable via env vars (`RATE_LIMIT_RPS`, `RATE_LIMIT_BURST`, allowlist for health/docs).
    ```
- Impact:
  - Rate limiting is not enforced by application code; public endpoints rely on external protection.
  - Preconditions: exposed API without external rate limiting.
- Notes:
  - Assumption: rate limiting is expected to be toggled via `RATE_LIMIT_ENABLED`.
  - Open question: Is rate limiting enforced at the proxy or WAF layer instead of in app code?

## Appendix

### Dependency and Version Notes
- Runtime dependencies in `requirements.txt` use lower-bound specifiers only (no lockfile or hashes).
- Dev/test dependencies in `requirements-dev.txt` are unpinned.

### Test/CI Health Summary
- No local tests or linters were executed during this audit.
- GitHub Actions workflows present: agent-canary, sdk-probe, workflow-tests, ci-smoke, legacy (disabled).

### Security Posture Notes
- Authentication is off by default unless `AUTH_ENABLED=1`.
- Debug/test endpoints and debug tracing are enabled in dev mode when `ENV` is unset.
- systemd unit runs the service as root.
- Rate limiting is documented but not enforced in application code.
