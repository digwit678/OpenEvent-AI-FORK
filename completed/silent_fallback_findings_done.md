# Silent fallback findings

## 1. Confirm date persistence silently ignores workflow failures (`backend/api/routes/messages.py:321-382`)
- `wf_process_msg` exceptions are only printed and `wf_res` stays `{}`, yet `_persist_confirmed_date` still returns a "Date confirmed" response and Step 3 footer as if persistence + logging succeeded.
- `_trigger_room_availability` errors are swallowed the same way, so the chat promises an availability follow-up even when the job never ran.
- Add a fallback block right after each failure: build `fallback_ctx = create_fallback_context("api.routes.messages.confirm_date", trigger="persistence_failed", event_id=conversation_state.event_id, thread_id=conversation_state.session_id, error=exc)` and wrap the reply with something explicit such as `wrap_fallback("I logged your confirmation, but our booking system didn't save the update. I've escalated it and will send availability as soon as it's synced.", fallback_ctx)`.

## 2. Availability workflow trigger failures stay invisible (`backend/api/routes/messages.py:267-318`)
- `_trigger_room_availability` catches every exception (missing DB, event not found, workflow crash) and only prints, yet the caller still pretends the re-check ran.
- When the helper exits early we should stash a diagnostic action in the conversation: e.g. `wrap_fallback("I couldn't rerun the availability scan because the event record was missing. I've asked a teammate to verify it manually and will follow up ASAP.", ctx)`.
- Surface the fallback in the chat response (perhaps append to the Step 3 footer) and attach a developer-facing action so we know to rerun the workflow manually.

## 3. Universal verbalizer hides LLM outages (`backend/ux/universal_verbalizer.py:385-461`)
- When the OpenAI key is absent, the LLM call raises, or verification fails, the function just returns the deterministic `fallback_text` with console logs like `[VERBALIZER_FALLBACK]`, so neither users nor QA can tell the tone-polisher failed.
- Wrap those branches with `wrap_fallback` so the chat clearly states that it's using the template: message idea — "Our tone reviewer is offline, so I'm sharing the raw confirmation text to avoid delays." Include the step/topic in the fallback context to speed up debugging.

## 4. ChatKit streaming silently falls back to workflow mode (`backend/agents/chatkit_runner.py:717-760`)
- Any SDK/network failure in `run_streamed` drops into `_fallback_stream` after a log warning; the UI keeps streaming as if the fancy mode worked, and devs don't know they lost tool telemetry.
- Before yielding fallback chunks, emit a diagnostic system message (or set `state["fallback_reason"]`) so the chat displays "Real-time streaming hit an issue, switching to safe workflow mode; responses may arrive one at a time." Include whether `OPENAI_AGENT_MODEL` or the SDK errored to aid triage.

## 5. Agent tool DB fallback returns empty data with no signal (`backend/agents/chatkit_runner.py:687-699`)
- `load_default_db_for_tools` returns `{"events": [], "tasks": []}` whenever the workflow DB can't be loaded, so downstream tools happily run against an empty dataset and reply "no event found" without revealing the real IO failure.
- Instead, propagate a structured error (or wrap a fallback message) so tool responses can say "Can't reach the booking database right now; please retry or contact support". That lets the chat surface a clear blocker instead of misleading "no data" results.
