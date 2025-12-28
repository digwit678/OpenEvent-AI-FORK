# Security Checklist: Backend & API (OpenEvent-AI)

**For:** Development Team / Co-founder
**Project:** OpenEvent AI Backend Integration
**Date:** 2025-12-09

---

## Priority Overview

| Priority | Items | When to Fix |
|----------|-------|-------------|
| 🔴 **MVP BLOCKER** | API key security, CORS configuration, endpoint protection, multi-tenant isolation | Before integration |
| 🟡 **MVP Recommended** | Rate limiting, input validation, secure logging | Before going live |
| 🟢 **Post-MVP** | Data encryption, audit logging, advanced session management | Within 1-2 weeks of launch |

---

## URGENT: Rotate Exposed OpenAI API Key

**An actual API key was found exposed in `.env.example` and may be in git history.**

The key starting with `sk-proj-cIa2MZ_...` was committed to the repository and must be rotated immediately.

### Steps to Rotate

1. Go to https://platform.openai.com/api-keys
2. Find the exposed key (starts with `sk-proj-cIa2MZ_`)
3. Click **"Revoke"** to immediately disable it
4. Click **"Create new secret key"** to generate a replacement
5. Update your local environment:
   - **macOS Keychain:** `security add-generic-password -a $USER -s openevent-api-test-key -w "NEW_KEY_HERE" -U`
   - **Or** set `OPENAI_API_KEY` environment variable
6. Verify by running: `pytest backend/tests/smoke/ -q`

### Git History Cleanup (Recommended before repo goes public)

```bash
# Install git-filter-repo if needed
pip install git-filter-repo

# Remove the exposed key from history (backup your repo first!)
git filter-repo --invert-paths --path .env.example
```

| Status | Action |
|--------|--------|
| ⬜ Key revoked on OpenAI dashboard | |
| ⬜ New key generated | |
| ⬜ Local environment updated | |
| ⬜ Tests pass with new key | |

---

## How to Use This Document

This checklist helps verify that your backend is secure before connecting to the frontend and Supabase.

- **Go through each section** and answer the questions
- **Check the boxes** (Yes/No) as you verify each item
- **If unsure**, the "How to Check" column tells you exactly where to look
- **Red flags** are marked clearly — these need immediate attention

---

## Section 1: API Key & Secrets Management

**🔴 Priority: MVP BLOCKER**

**What is this?** API keys (OpenAI, Supabase) grant access to paid services and sensitive data. Exposed keys can lead to unauthorized usage and billing charges.

**Risk if not done:** Attackers can use your API keys to consume your OpenAI credits, access your database, or impersonate your service.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 1.1 | Is `.env.example` using placeholder values only? | Open `.env.example`, verify no real keys (no `sk-` prefixes) | ⬜ Yes  ⬜ No |
| 1.2 | Is `.env` file in `.gitignore`? | Run: `grep -q "\.env" .gitignore && echo "Found"` | ⬜ Yes  ⬜ No |
| 1.3 | Are API keys loaded securely? | Review `backend/utils/openai_key.py` - should use keychain or env vars | ⬜ Yes  ⬜ No |
| 1.4 | No API keys in git history? | Run: `git log -p --all -S "sk-" -- "*.py" "*.env*"` | ⬜ Clean  ⬜ Found (rotate!) |
| 1.5 | Supabase `service_role` key protected? | Only in environment/keychain, never in code | ⬜ Yes  ⬜ No |

### Key Management Best Practices

| Key Type | Where to Store | Never Put In |
|----------|----------------|--------------|
| OpenAI API Key | macOS Keychain or env var | `.env.example`, git history, logs |
| Supabase `service_role` | Environment variable | Frontend code, git, logs |
| Supabase `anon` | Frontend code (OK) | Backend-only operations |

### Verification Commands

```bash
# Check for exposed keys in codebase
grep -r "sk-proj-" --include="*.py" --include="*.env*" --include="*.sh" .

# Check git history for secrets
git log -p --all -S "sk-" | head -50

# Verify .gitignore patterns
cat .gitignore | grep -E "\.env|secret|key"
```

---

## Section 2: API Endpoint Security

**🔴 Priority: MVP BLOCKER**

**What is this?** API endpoints must be protected to prevent unauthorized access. Dangerous endpoints (like data deletion) must be disabled in production.

**Risk if not done:** Anyone can call your API endpoints to read, modify, or delete data without authentication.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 2.1 | Is `/api/client/reset` protected? | Endpoint should return 403 unless `ENABLE_DANGEROUS_ENDPOINTS=true` | ⬜ Yes  ⬜ No |
| 2.2 | Is `ENABLE_DANGEROUS_ENDPOINTS` set to `false` in production? | Check environment config | ⬜ Yes  ⬜ No |
| 2.3 | Are debug endpoints disabled? | `DEBUG_TRACE_ENABLED` should be `false` in production | ⬜ Yes  ⬜ No |
| 2.4 | Are there any other destructive endpoints? | Search for `DELETE` or `reset` in `backend/main.py` | ⬜ Reviewed  ⬜ Not checked |

### Dangerous Endpoints Inventory

| Endpoint | Purpose | Protection Required |
|----------|---------|---------------------|
| `/api/client/reset` | Delete all client data | `ENABLE_DANGEROUS_ENDPOINTS=true` required |
| `/api/debug/*` | Expose trace data | `DEBUG_TRACE_ENABLED` flag |
| `/api/tasks/cleanup` | Remove tasks | Review access controls |

### Verification Test

```bash
# Test that dangerous endpoint is blocked (should return 403)
curl -X POST http://localhost:8000/api/client/reset \
  -H "Content-Type: application/json" \
  -d '{"email": "test@test.com"}'

# Expected: {"detail": "This endpoint is disabled..."}
```

---

## Section 3: CORS Configuration

**🔴 Priority: MVP BLOCKER**

**What is this?** CORS (Cross-Origin Resource Sharing) controls which websites can call your API. Misconfigured CORS allows attacks from malicious websites.

**Risk if not done:** Attackers can create fake websites that steal data from your API by making requests from users' browsers.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 3.1 | Are allowed origins explicitly listed (not `*`)? | Review `backend/main.py` CORS config | ⬜ Specific origins  ⬜ Wildcard (*) |
| 3.2 | Is `ALLOWED_ORIGINS` environment variable set? | Check `.env` file or environment | ⬜ Yes  ⬜ No |
| 3.3 | Does production config specify your domain? | e.g., `https://yourdomain.com` | ⬜ Yes  ⬜ No |

### Current Configuration

```python
# In backend/main.py - this should be set:
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
```

### Environment Variable Examples

| Environment | `ALLOWED_ORIGINS` Value |
|-------------|-------------------------|
| Local Development | `http://localhost:3000` |
| Staging | `https://staging.yourdomain.com` |
| Production | `https://yourdomain.com,https://app.yourdomain.com` |

### Verification Test

```bash
# Test CORS from different origin (should be blocked)
curl -H "Origin: https://evil.com" \
     -H "Access-Control-Request-Method: GET" \
     -X OPTIONS \
     http://localhost:8000/api/events

# Check response headers - should NOT include evil.com
```

---

## Section 4: Multi-Tenant Data Isolation

**🔴 Priority: MVP BLOCKER**

**What is this?** Multi-tenant isolation ensures Team A cannot see Team B's data. This is enforced through `team_id` filtering in all database queries.

**Risk if not done:** Data leakage between teams — one customer can see another customer's events, clients, and offers.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 4.1 | Do all Supabase queries include `team_id` filter? | Review `backend/workflows/io/integration/supabase_adapter.py` | ⬜ Yes  ⬜ No |
| 4.2 | Is `OE_TEAM_ID` environment variable set? | Check environment config | ⬜ Yes  ⬜ No |
| 4.3 | Are RLS policies enabled in Supabase? | See frontend checklist Section 1 | ⬜ Yes  ⬜ No |
| 4.4 | Has cross-team access been tested? | Create events in Team A, verify Team B cannot see them | ⬜ Tested  ⬜ Not tested |

### Query Pattern Review

Every Supabase query should include team_id:

```python
# CORRECT - includes team_id filter
response = supabase.table("events")\
    .select("*")\
    .eq("team_id", team_id)\
    .execute()

# WRONG - missing team_id (can see all teams' data!)
response = supabase.table("events")\
    .select("*")\
    .execute()
```

### Critical Files to Review

- `backend/workflows/io/integration/supabase_adapter.py` - All database operations
- `backend/workflows/io/integration/config.py` - Team ID configuration

---

## Section 5: Input Validation

**🟡 Priority: MVP Recommended**

**What is this?** Input validation ensures user-provided data is safe and correctly formatted before processing.

**Risk if not done:** Malformed input can cause crashes, SQL injection (if using raw queries), or data corruption.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 5.1 | Are email addresses validated? | Check extraction and storage code | ⬜ Yes  ⬜ No |
| 5.2 | Are UUIDs validated before database queries? | Review adapter code for UUID validation | ⬜ Yes  ⬜ No |
| 5.3 | Are text inputs length-limited? | Check Pydantic models for `max_length` | ⬜ Yes  ⬜ No |
| 5.4 | Is HTML/script content sanitized? | Check message handling code | ⬜ Yes  ⬜ No |

### Pydantic Model Example

```python
from pydantic import BaseModel, EmailStr, Field

class ClientRequest(BaseModel):
    email: EmailStr  # Validates email format
    name: str = Field(..., max_length=200)  # Length limit
    notes: str = Field(default="", max_length=5000)  # Length limit
```

---

## Section 6: Prompt Injection Protection

**🟡 Priority: MVP Recommended**

**What is this?** Prompt injection is an attack where malicious users craft input that manipulates the AI's behavior, potentially bypassing safety measures or extracting sensitive information.

**Risk if not done:** Attackers could manipulate AI responses, extract system prompts, bypass business logic, or cause the AI to behave unexpectedly.

### Current Protections

| Protection | Status | Notes |
|------------|--------|-------|
| Human-in-the-Loop (HIL) gate | ✅ Active | All AI responses require manager approval |
| Regex→NER→LLM pipeline | ✅ Active | Reduces raw text exposure to LLM |
| Input sanitization utility | ✅ Added | `backend/workflows/llm/sanitize.py` |
| Prompt injection test suite | ✅ Added | `backend/tests/regression/test_security_prompt_injection.py` |

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 6.1 | Is user input sanitized before LLM calls? | Review LLM adapter for sanitization | ⬜ Yes  ⬜ No |
| 6.2 | Are suspicious patterns detected? | Check `check_prompt_injection()` usage | ⬜ Yes  ⬜ No |
| 6.3 | Are prompt injection tests passing? | Run: `pytest backend/tests/regression/test_security_prompt_injection.py` | ⬜ Pass  ⬜ Fail |
| 6.4 | Is manager custom prompt feature sandboxed? | If implemented, use enum-based options only | ⬜ Yes  ⬜ N/A |

### Usage Example

```python
from backend.workflows.llm.sanitize import (
    sanitize_for_llm,
    sanitize_message,
    check_prompt_injection,
    wrap_user_content,
)

# Sanitize before LLM call
safe_body = sanitize_for_llm(email_body, max_length=10000)

# Check for injection attempts
is_suspicious, pattern = check_prompt_injection(user_message)
if is_suspicious:
    log.warning(f"Potential injection detected: {pattern}")

# Wrap user content with delimiters
wrapped = wrap_user_content(client_notes, label="CLIENT_NOTES")
```

### Attack Patterns Detected

The sanitization utility detects:
- Instruction override attempts ("ignore previous instructions")
- Role hijacking ("you are now", "act as", "pretend to be")
- System prompt extraction ("reveal your instructions")
- Delimiter injection (`<system>`, `[SYSTEM]`)
- DAN-style jailbreaks ("do anything now")

### Files to Review

- `backend/workflows/llm/sanitize.py` - Sanitization utilities
- `backend/workflows/llm/adapter.py` - Where sanitization should be applied
- `backend/adapters/agent_adapter.py` - Raw input handling

---

## Section 7: Rate Limiting

**🟡 Priority: MVP Recommended**

**What is this?** Rate limiting prevents abuse by limiting how many requests a user/IP can make in a time period.

**Risk if not done:** Attackers can overwhelm your API (DoS), or abuse expensive operations (like LLM calls) to run up your costs.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 6.1 | Is rate limiting middleware installed? | Run: `pip show slowapi` | ⬜ Installed  ⬜ Not installed |
| 6.2 | Are conversation endpoints rate-limited? | Review `backend/main.py` for limiter decorators | ⬜ Yes  ⬜ No |
| 6.3 | Are LLM-calling endpoints protected? | These are expensive — should have lower limits | ⬜ Yes  ⬜ No |

### Implementation Example

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter

@app.post("/api/conversation")
@limiter.limit("10/minute")  # 10 requests per minute per IP
async def conversation_endpoint(request: Request):
    ...
```

---

## Section 8: Logging & Error Handling

**🟡 Priority: MVP Recommended**

**What is this?** Logging helps with debugging but can expose sensitive information. Error messages should be generic for clients but detailed for developers.

**Risk if not done:** Logs may leak PII (emails, names), API keys, or internal paths that help attackers.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 7.1 | Are `print()` statements replaced with `logging`? | Search for `print(` in `backend/` | ⬜ Yes  ⬜ No |
| 7.2 | Is PII (email, name) excluded from logs? | Review log statements for sensitive fields | ⬜ Yes  ⬜ No |
| 7.3 | Are stack traces hidden from API responses? | Test error responses in production mode | ⬜ Hidden  ⬜ Exposed |
| 7.4 | Are API keys masked in logs? | Search for API key patterns in log output | ⬜ Yes  ⬜ No |

### Logging Best Practices

```python
import logging

logger = logging.getLogger(__name__)

# GOOD - generic message
logger.info("Processing event %s", event_id)

# BAD - exposes PII
logger.info("Processing event for %s", client_email)

# GOOD - error without stack trace to client
except Exception as e:
    logger.exception("Internal error processing request")
    raise HTTPException(status_code=500, detail="Internal server error")
```

---

## Section 9: Data Encryption

**🟢 Priority: Post-MVP**

**What is this?** Encryption protects data at rest and in transit. Sensitive fields (PII) should be encrypted in the database.

**Risk if not done:** If database is accessed by attacker, all PII is immediately readable.

### Checklist

| # | Question | How to Check | Status |
|---|----------|--------------|--------|
| 8.1 | Is disk encryption enabled (FileVault/BitLocker)? | Check system settings | ⬜ Yes  ⬜ No |
| 8.2 | Is the JSON database file permission-restricted? | Run: `ls -la events_database.json` | ⬜ 0600  ⬜ Other |
| 8.3 | Are sensitive fields encrypted in storage? | Review database schema | ⬜ Yes  ⬜ No |
| 8.4 | Is data transferred over HTTPS only? | Check production URLs | ⬜ Yes  ⬜ No |

### PII Fields in System

These fields contain personally identifiable information:

| Table/Store | Fields | Encryption Status |
|-------------|--------|-------------------|
| clients | email, name, phone, company | ⬜ Encrypted  ⬜ Plaintext |
| events | client contact info, notes | ⬜ Encrypted  ⬜ Plaintext |
| emails | to, from, body content | ⬜ Encrypted  ⬜ Plaintext |

---

## Section 10: Quick Self-Test (3 Minutes)

Do these tests yourself right now:

### Test A: Dangerous Endpoint Protection

```bash
# Should return 403 Forbidden
curl -X POST http://localhost:8000/api/client/reset \
  -H "Content-Type: application/json" \
  -d '{"email": "test@test.com"}'
```

| Result | Status |
|--------|--------|
| Returns 403 with "endpoint disabled" message | ✅ SECURE |
| Returns 200 or deletes data | ❌ FIX: Set `ENABLE_DANGEROUS_ENDPOINTS=false` |

### Test B: CORS Protection

Open browser DevTools (F12) on a random website and run:

```javascript
fetch('http://localhost:8000/api/events')
  .then(r => console.log('Allowed!', r))
  .catch(e => console.log('Blocked:', e))
```

| Result | Status |
|--------|--------|
| Request blocked by CORS | ✅ SECURE |
| Request succeeds | ❌ FIX: Configure `ALLOWED_ORIGINS` |

### Test C: API Key Security

```bash
# Check for exposed keys
grep -r "sk-proj-" --include="*.py" --include="*.env*" .
```

| Result | Status |
|--------|--------|
| No matches found | ✅ SECURE |
| Keys found in files | ❌ FIX: Remove keys and rotate |

---

## Section 11: Summary Scorecard

Fill this in after completing the checklist:

| Category | Priority | Status | Action Needed |
|----------|----------|--------|---------------|
| **API Key Rotated (OpenAI)** | 🔴 | ⬜ Pass  ⬜ Fail | |
| **No Secrets in `.env.example`** | 🔴 | ⬜ Pass  ⬜ Fail | |
| **Dangerous Endpoints Protected** | 🔴 | ⬜ Pass  ⬜ Fail | |
| **CORS Configured (not `*`)** | 🔴 | ⬜ Pass  ⬜ Fail | |
| **Multi-Tenant Isolation** | 🔴 | ⬜ Pass  ⬜ Fail | |
| **Prompt Injection Protection** | 🟡 | ⬜ Pass  ⬜ Fail | |
| **Rate Limiting Enabled** | 🟡 | ⬜ Pass  ⬜ Fail | |
| **Input Validation** | 🟡 | ⬜ Pass  ⬜ Fail | |
| **Secure Logging (no PII)** | 🟡 | ⬜ Pass  ⬜ Fail | |
| **Data Encryption** | 🟢 | ⬜ Pass  ⬜ Fail | |

### Overall Security Status

| All 🔴 Critical Items Pass? | Ready for Integration? |
|-----------------------------|------------------------|
| ✅ Yes | ✅ Ready to proceed |
| ❌ No | ❌ Fix critical items first |

---

## Section 12: For Your Developer

### Check for Exposed Secrets

```bash
# Search for API keys in code and git history
git log -p --all -S "sk-" -- "*.py" "*.env*" "*.sh"
grep -r "sk-proj-" --include="*.py" --include="*.env*" .

# Search for Supabase service role key
grep -r "service_role" --include="*.js" --include="*.ts" --include="*.py" .
```

### Verify CORS Configuration

```python
# In backend/main.py, ensure this pattern:
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,  # NOT ["*"]
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

### Test Endpoint Protection

```bash
# Test dangerous endpoint is blocked
curl -X POST http://localhost:8000/api/client/reset \
  -H "Content-Type: application/json" \
  -d '{"email": "test@test.com"}'
# Expected: 403 Forbidden

# Test with flag enabled (dev only!)
ENABLE_DANGEROUS_ENDPOINTS=true python -m uvicorn backend.main:app
# Now the endpoint should work
```

### Enable Rate Limiting

```bash
# Install slowapi
pip install slowapi

# Add to backend/main.py
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Apply to endpoints
@app.post("/api/conversation")
@limiter.limit("10/minute")
async def conversation(request: Request):
    ...
```

---

## Questions?

If you're unsure about any item:

1. **Mark it as "Unknown"** in the checklist
2. **Share this document** with your team
3. **Ask for verification** before proceeding with integration

Security issues should be fixed **before** connecting the AI workflow to production systems.

---

*Document version: 1.0 | Created: 2025-12-09*
*Companion to: SECURITY_CHECKLIST_FRONTEND_SUPABASE.md*
