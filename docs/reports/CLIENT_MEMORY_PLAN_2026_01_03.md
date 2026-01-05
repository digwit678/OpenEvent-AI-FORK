# Client Memory / Personalization Plan (03.01.26)

## Goal
Collect and persist client-specific information and message history so the agent can personalize responses for the current client. Only the current client’s history is accessible in their session.

## Non-Goals (for now)
- Cross-client recommendations or shared insights.
- Long-term analytics or marketing automation.
- Full vector search across all clients (defer to later).

## Key Requirements
- Client data is isolated per client and per tenant (team/manager).
- The agent only receives memory for the current client.
- Compatible with JSON DB now; Supabase later.
- Safe defaults: no PII leakage between clients.

## Data Model (JSON First)
Add a `client_memory` section in the JSON DB:
```json
{
  "client_memory": {
    "client_id_or_email": {
      "profile": {
        "name": "...",
        "company": "...",
        "language": "...",
        "preferences": ["..."],
        "notes": ["..."]
      },
      "history": [
        {"ts": "...", "role": "client", "text": "..."},
        {"ts": "...", "role": "assistant", "text": "..."}
      ],
      "summary": "short personalization summary",
      "last_updated": "..."
    }
  }
}
```
- Keyed by normalized client email or client UUID.
- Stored under the same tenant file in JSON mode (`events_<team>.json`).

## Pipeline (Minimal First Version)
1) **Ingest**: Append each incoming client message to that client’s history.
2) **Summarize**: Update a short profile summary after N messages or on session end.
3) **Retrieve**: At session start, load the client’s summary + last K messages.
4) **Inject**: Provide memory to the agent as context for personalization.

## Access Control
- Use tenant context to choose the correct JSON file.
- Only fetch memory for the current client (by email/client_id).
- Never merge memory across clients.

## Integration Points
- `backend/api/routes/messages.py`
  - At message receipt: call `client_memory.append()`.
  - On response: optionally store assistant message for continuity.
- `backend/workflows/steps/step1_intake/trigger/step1_handler.py`
  - Use captured client info to seed profile.
- `backend/workflows/qna/*` or agent adapter
  - Inject memory summary into prompt or agent context.

## Supabase Phase (Later)
- Create `client_memory` table keyed by `client_id` + `team_id`.
- Enforce RLS on `team_id`.
- Add `last_updated`, `summary`, and optional `vector_embedding` columns.

## Config Toggles
- `CLIENT_MEMORY_ENABLED=0|1` (default 0)
- `CLIENT_MEMORY_MAX_MESSAGES=50` (cap history)
- `CLIENT_MEMORY_SUMMARY_INTERVAL=10` (summarize every N messages)

## Risks / Mitigations
- **PII leakage**: enforce tenant+client scoping everywhere.
- **Prompt bloat**: only include short summary + last K messages.
- **Stale info**: re-summarize periodically and store last_updated.

## Next Steps
1) Implement JSON schema + append functions.
2) Wire ingestion at `/api/send-message` and `/api/start-conversation`.
3) Add summary generator (LLM or rule-based) behind toggle.
4) Add unit tests for isolation and correct retrieval.
5) Plan Supabase schema + RLS for production.
