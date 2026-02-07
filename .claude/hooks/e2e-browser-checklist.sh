#!/bin/bash
# E2E Browser Testing Context Injection Hook
# Fires on UserPromptSubmit when user mentions e2e/browser/playwright keywords.
# Injects hard-learned lessons to avoid wasting time on avoidable mistakes.

INPUT=$(cat)
PROMPT=$(echo "$INPUT" | jq -r '.prompt // empty' 2>/dev/null)

# If we can't parse the prompt, exit silently
if [ -z "$PROMPT" ]; then
  exit 0
fi

# Match if user mentions e2e, browser testing, or playwright
if echo "$PROMPT" | grep -iE "(e2e|browser.?test|playwright|end.to.end|browser.?verif)" > /dev/null 2>&1; then
  cat << 'HOOK_EOF'

=== E2E BROWSER TESTING — MANDATORY CHECKLIST ===

You MUST follow these rules for browser E2E testing. These are hard-learned
from repeated failures and wasted time.

### 1. ALWAYS USE UNIQUE EMAILS (CRITICAL)
- Generate: `e2e-browser-<timestamp>@example.com`
- NEVER use `unknown@example.com` — the frontend defaults to this and
  it collides with previous test sessions
- NEVER reuse emails from prior sessions — "Welcome back" flows break assertions

### 2. USE API-DRIVEN APPROACH (NOT UI INPUT)
- Call `/api/start-conversation` and `/api/send-message` directly via
  `fetch()` in the browser console — this bypasses:
  - React input injection quirks (`__reactProps$*` / onChange)
  - Frontend's `extractEmail()` returning `unknown@example.com`
  - `_extract_workflow_reply()` interceptions for HIL actions
- Display results in a custom overlay div for visual verification

### 3. TWO RESPONSE PIPELINES — KNOW THE DIFFERENCE
- Main page (`/api/send-message`): Uses `_extract_workflow_reply()` which
  intercepts `offer_waiting_hil` with generic "Thanks for confirming!" text
- Agent page (`chatkit/respond`): Uses `_compose_reply()` which extracts
  directly from draft messages (no action filtering)
- For E2E: prefer API-driven approach that shows raw backend responses

### 4. RESET STALE STATE BEFORE TESTING
- `POST /api/client/reset` with `{"email": "<email>"}` to clear stale events
- Backend needs `ENABLE_DANGEROUS_ENDPOINTS=true` (set by dev_server.sh)
- After reset, verify with a fresh curl call before browser testing

### 5. REFERENCE SCENARIO DOCS
- Read `e2e-scenarios/` folder for latest reference flows
- Match the flow structure closely (variations in verbalizer OK, not structure)
- Current reference: `e2e-scenarios/2026-02-06_offer-flow-and-cancellation.md`

### 6. INSTALL FETCH INTERCEPTOR FOR DEBUGGING
```javascript
window.__e2eLog = [];
const origFetch = window.fetch;
window.fetch = async function(...args) {
  const resp = await origFetch.apply(this, args);
  // ... capture and log API responses
  return resp;
};
```

### 7. CHROME EXTENSION CAVEATS
- Claude-in-Chrome disconnects intermittently — use `tabs_context_mcp` to check
- Playwright MCP can't launch when Chrome is already running
- Always create NEW tabs via `tabs_create_mcp`, never reuse stale tab IDs
- For React inputs: use `__reactProps$*` onChange injection, NOT native Events

### 8. DEV MODE BEHAVIOR
- `ENV=dev` skips `enqueue_hil_tasks` — no pending_hil_requests created
- All drafts treated as immediate (no approval needed)
- `ENABLE_DANGEROUS_ENDPOINTS=true` enables /api/client/reset

=== END E2E CHECKLIST ===

HOOK_EOF
fi

exit 0
