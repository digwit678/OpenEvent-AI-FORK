# OpenEvent Agent & ChatKit Setup

This guide explains how to run the workflow-backed agent locally with the
OpenAI Agents SDK and ChatKit UI.

## 1. Prerequisites

1. **Python packages**

   ```bash
   cd ~/PycharmProjects/OpenEvent-AI
   export OPENAI_API_KEY="$(security find-generic-password -a \"$USER\" -s 'openevent-api-test-key' -w)"
   python3 -m pip install --upgrade openai openai-agents openai-chatkit fastapi uvicorn pydantic
   ```

2. **Frontend packages** (Next.js app in `atelier-ai-frontend`)

   ```bash
   cd atelier-ai-frontend
   npm install
   ```

3. **Environment variables**

   ```bash
   export NEXT_PUBLIC_BACKEND_BASE=http://localhost:8000
   export NEXT_PUBLIC_CHATKIT_DOMAIN_KEY=local-development
   export CHATKIT_DOMAIN_KEY=${NEXT_PUBLIC_CHATKIT_DOMAIN_KEY}
   export VERBALIZER_TONE=empathetic
   ```

   `CHATKIT_DOMAIN_KEY` must match the value configured in the ChatKit UI.

## 2. Running the backend

```bash
cd ~/PycharmProjects/OpenEvent-AI
uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
```

The FastAPI app exposes:

- `/api/agent/reply` – JSON API returning `{assistant_text, requires_hil, action, payload}`.
- `/api/chatkit/respond` – SSE endpoint for ChatKit custom backend mode.
- `/api/chatkit/upload` – direct-upload stub for attachments.

## 3. Running the Agent UI

```bash
cd atelier-ai-frontend
npm run dev
```

Visit `http://localhost:3000/agent` for the ChatKit interface. The frontend now
fetches a client secret from `/api/chatkit/session`, embeds the hosted
`chatkit.js` script, and connects to the custom backend responder. Quick-action
buttons appear whenever the assistant proposes `Confirm Offer | Change Offer |
Discard Offer`.

## 4. One-command dev workflow

Running the backend now orchestrates the entire dev stack:

```bash
python3 backend/main.py
```

During startup the backend will:

1. Ensure `OPENAI_API_KEY`, `AGENT_MODE=openai`, and `VERBALIZER_TONE=empathetic` are set.
2. Free port 8000 if another process is using it.
3. Start (or reuse) the Next.js dev server on the first free port from 3000/3001/3002 and
   set `NEXT_PUBLIC_BACKEND_BASE=http://localhost:8000` automatically.
4. Shut the frontend down when the backend process exits.

Logs include the chosen frontend port and whether autostart was required. A
pidfile is written to `.dev/frontend.pid` so repeated backend launches avoid
spawning duplicate frontend processes.

## 5. Capability Q&A & Resume Flow

- **Precedence** – Step inputs (dates, rooms, offers, visits) are processed
  first. General questions from the same message are answered in the same turn;
  when they reference the upcoming step they render as INFO blocks before the
  deterministic step draft, otherwise they appear afterwards.
- **Capability Q&A** – Every question expands into an `INFO:` block followed by
  `NEXT STEP:` → `Proceed with <Step>?`. The deterministic facts are sourced
  from catalog helpers so the workflow state never changes during Q&A.
- **Resume prompts** – Affirmatives (`yes`, `ok`, `proceed`) immediately resume
  the current step. The UI now surfaces a “Proceed with <Step>” quick-reply that
  sends a plain `yes` back to the backend.
- **Agents SDK** – The custom ChatKit runner (`backend/chatkit/server.py`) now
  boots a step-aware agent. Engine tools are auto-executed only when the current
  step allows them (see `backend/agents/chatkit_runner.py`); client actions
  (`Confirm Offer`, `Change Offer`, `Discard Offer`, `See Catering`, `See
  Products`) are delivered via StopAtTools so the GUI can capture the click.
- **Prerequisite checks** – Explicit room nominations during Step 3 now enforce
  layout-aware capacity checks. Shortfalls list deterministic alternatives and
  keep the workflow on Step 3 until the client picks a viable room.
- **Message Manager intent** – Requests such as “please ask your manager” enqueue
  a `message_manager` task and reply with an INFO/NEXT STEP block so the client
  remains on the current step.
- **Privacy guards** – Q&A answers only surface venue inventory and generic
  availability; no other client data is ever exposed. Thread handling remains
  scoped to the active `thread_id` (both backend and UI).

## 6. Notes

- After a manual review is approved the backend now immediately advances the
  conversation and returns a single assistant reply that includes the approval
  acknowledgement plus the next workflow step. Chats remain scoped by
  `thread_id`, so approvals for other threads never surface in the active view.
- The deterministic engine (workflow steps, detours, hashes, persistence) always
  governs behaviour. The agent layer only influences tone.
- `VERBALIZER_TONE=empathetic` (default) routes replies through the LLM tone
  layer. `VERBALIZER_TONE=plain` keeps the raw deterministic copy and is
  recommended for CI or emergency fallback.
- All database writes continue to flow through existing workflow functions; the
  agent layer never mutates the DB directly.
- Only Step 4b (products mini-loop) auto-sends responses. All other steps set
  `requires_hil=true` so drafts surface in the manager approval lane.
- `VERBALIZER_TONE` now defaults to `plain` unless explicitly set to
  `empathetic` or `EMPATHETIC_VERBALIZER=true/1/yes`. Use the empathetic mode
  only when running with networked LLM access.
- `AUTO_LOCK_SINGLE_ROOM=false` prevents implicit room auto-locking after date
  confirmation; set to `true` if you explicitly need single-room auto-locking.

### Test recipes

- `PYTHONPATH=. pytest backend/tests/test_agents_sdk_allowlist.py` – verifies
  the per-step tool allowlist rejects off-step engine tools while allowing
  StopAtTools client actions.
- `PYTHONPATH=. pytest backend/tests/test_agent_api.py` – exercises the REST
  facade and guardrails envelope.
- `PYTHONPATH=. pytest backend/tests/test_verbalizer_agent.py` – ensures header
  preservation and empathetic tone fallbacks remain intact.
