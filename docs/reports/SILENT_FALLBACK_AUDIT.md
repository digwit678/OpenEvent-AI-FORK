# Silent fallback audit (backend)

Last updated: 2026-01-06

Scope: legacy fallbacks in backend workflows that do not emit a fallback diagnostic or explicit "this is a fallback" message. These are "silent" from the debugging perspective. This list is intended to track legacy/silent fallback paths and their eventual unsilencing.

## Still silent (needs follow-up)

| Area | Location | Behavior | Why it is silent | Status |
| --- | --- | --- | --- | --- |
| Step1 intake change propagation fallback (legacy) | `backend/workflows/steps/step1_intake/trigger/step1_handler.py:973` | Legacy date-change fallback runs when change propagation yields no change; updates `chosen_date` + routing without messaging. | No fallback wrapper or diagnostic message emitted. | silent |
| Step1 requirements change fallback (legacy) | `backend/workflows/steps/step1_intake/trigger/step1_handler.py:1022` | Legacy requirements-change detection reroutes to Step 3 and clears negotiation state. | No fallback wrapper or diagnostic message emitted. | silent |
| Step1 room change fallback (legacy) | `backend/workflows/steps/step1_intake/trigger/step1_handler.py:1032` | Legacy room-change detection reroutes to Step 3 based on extracted room. | No fallback wrapper or diagnostic message emitted. | silent |

## Unsilenced (tracked for history)

| Area | Location | Behavior | When unsilenced | Notes |
| --- | --- | --- | --- | --- |
| Gemini API fallback | `backend/adapters/agent_adapter.py:610-622` | GeminiAgentAdapter falls back to StubAgentAdapter when Gemini API fails | 2026-01-06 | Now prints LOUD `[GEMINI FALLBACK]` message with error details |
| OpenAI API fallback (intent) | `backend/adapters/agent_adapter.py:472-477` | OpenAIAgentAdapter.route_intent falls back to StubAgentAdapter on error | 2026-01-06 | Now prints LOUD `[OPENAI FALLBACK]` message with error details |
| OpenAI API fallback (entities) | `backend/adapters/agent_adapter.py:496-501` | OpenAIAgentAdapter.extract_entities falls back to StubAgentAdapter on error | 2026-01-06 | Now prints LOUD `[OPENAI FALLBACK]` message with error details |
