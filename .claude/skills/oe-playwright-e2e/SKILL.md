---
name: oe-playwright-e2e
description: Official Playwright E2E testing protocol. Triggers on "E2E", "Playwright", "browser test". Enforces fresh client state, hybrid mode, and clean ports.
---

# oe-playwright-e2e — Browser E2E Testing Protocol

## Golden Rule: API-Driven Browser Verification

Do NOT fight with React input injection. Instead:
1. Open `http://localhost:3000` in a fresh browser tab
2. Create a custom overlay div via `javascript_tool`
3. Make `fetch()` calls directly to backend API endpoints
4. Display responses in the overlay for visual verification

This approach avoids: React `onChange` quirks, `extractEmail()` defaulting to
`unknown@example.com`, `_extract_workflow_reply()` HIL interceptions, and
streaming/loading state bugs.

### API-Driven Template

```javascript
// In browser console via javascript_tool:
const email = 'e2e-browser-' + Date.now() + '@example.com';
const res = await fetch('http://localhost:8000/api/start-conversation', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ email_body: "...", client_email: email })
}).then(r => r.json());
// Display res.response in overlay div
```

## 1. Prerequisites

### Port Hygiene
- Check `lsof -i :3000` and `lsof -i :8000`
- Kill unexpected processes if necessary

### Environment
- Backend: `./scripts/dev/dev_server.sh` (sets `ENV=dev`, `ENABLE_DANGEROUS_ENDPOINTS=true`)
- Frontend: `cd atelier-ai-frontend && npm run dev`
- Ensure `AGENT_MODE` is appropriate (not `stub` for real E2E)

### Fresh Client (MANDATORY)
- **ALWAYS generate a unique email**: `e2e-browser-<timestamp>@example.com`
- **NEVER use `unknown@example.com`** — this is the frontend's default and
  collides with stale test data from previous sessions
- **Reset stale state** before testing:
  ```bash
  curl -s -X POST http://localhost:8000/api/client/reset \
    -H "Content-Type: application/json" \
    -d '{"email": "unknown@example.com"}'
  ```

## 2. Reference Scenarios

**ALWAYS read the latest reference scenario doc before running E2E:**

```
e2e-scenarios/
├── 2026-02-06_offer-flow-and-cancellation.md  ← LATEST (9-step flow, 2 offers)
├── 2026-01-21_hybrid-detour-second-offer-site-visit.md
└── 2026-01-19_accessibility-rate-inclusions-qna.md
```

The reference scenario defines the expected flow structure. Match it closely —
variations in verbalizer wording are OK, but the step sequence must match.

## 3. Two Response Pipelines (Critical Knowledge)

| Endpoint | Function | Behavior |
|----------|----------|----------|
| `/api/send-message` | `_extract_workflow_reply()` | Intercepts `offer_waiting_hil` → "Thanks for confirming!" |
| `chatkit/respond` | `_compose_reply()` | Direct draft extraction, no action filtering |

If you see "Thanks for confirming!" on a new inquiry, the email matched an
existing event with `pending_hil_requests` or `negotiation_pending_decision`.
Reset the client and use a unique email.

## 4. Standard E2E Flow (from reference scenario)

1. **Initial inquiry** with date + time + guest count
   - Verify: April dates preserved (BUG-055), room availability shown
2. **Room selection** → First Offer
   - Verify: `offer_draft_prepared` action, pricing shown (BUG-053)
3. **Hybrid accept + Q&A** (e.g., "I accept. Do you have catering?")
   - Verify: Both acceptance AND Q&A in response (BUG-054)
4. **Date change detour** → Second Offer
   - Verify: New date in offer, April preserved (BUG-055)
5. **Accept + billing**
   - Verify: Deposit gate or approval flow
6. **Cancellation**
   - Verify: `event_cancelled_deleted`, date/room released

### Bug Verification Checks

| Bug | Check | Pass Criteria |
|-----|-------|---------------|
| BUG-053 | Room selection → offer | `hasOffer && !hasThanksConfirm` |
| BUG-054 | Hybrid message | Response has BOTH workflow action AND Q&A |
| BUG-055 | Dateless follow-up | Response references original month (not today) |
| BUG-056 | Time after promotion | No "what time" re-ask after Step 2 |

## 5. Debugging Tools

### Fetch Interceptor (install in browser)
```javascript
window.__e2eLog = [];
const origFetch = window.fetch;
window.fetch = async function(...args) {
  const resp = await origFetch.apply(this, args);
  const url = typeof args[0] === 'string' ? args[0] : args[0]?.url || '';
  if (url.includes('/api/')) {
    const clone = resp.clone();
    try {
      const data = await clone.json();
      window.__e2eLog.push({ url, data, ts: new Date().toISOString() });
    } catch(e) {}
  }
  return resp;
};
```

### Direct curl verification
```bash
curl -s -X POST http://localhost:8000/api/start-conversation \
  -H "Content-Type: application/json" \
  -d '{"email_body": "...", "client_email": "e2e-curl-test@example.com"}' \
  | python3 -m json.tool
```

## 6. Chrome Extension Caveats

- **Playwright MCP can't launch when Chrome is already running** — use Claude-in-Chrome extension
- **Extension disconnects intermittently** — use `tabs_context_mcp` to check
- **Always create NEW tabs** via `tabs_create_mcp` — never reuse stale tab IDs
- **React input injection**: Use `__reactProps$*` key + `props.onChange()`, NOT native Events
- **Textarea has `onKeyPress` not `onKeyDown`** for submit handling

## 7. Common Pitfalls

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Thanks for confirming!" | Stale event with pending_hil | Reset client, use unique email |
| "Welcome back" | Reused email | Generate `e2e-<timestamp>@example.com` |
| February dates (not April) | BUG-055: date drift | Check `resolve_anchor_date()` fallback |
| Time re-asked | BUG-056: field promotion gap | Check both `captured` and `verified` |
| Q&A dropped | BUG-054: early halt=True | Check pre-route Q&A generation |
| isLoading stuck | Frontend streaming bug | Use `response.text()` not `getReader()` |
| ChatKit not rendering | OpenAI CDN failure | Use main page with API-driven approach |
