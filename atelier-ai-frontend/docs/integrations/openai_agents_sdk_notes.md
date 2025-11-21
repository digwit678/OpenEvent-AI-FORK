# OpenAI Agents SDK & ChatKit — Code Patterns (Multi-Agent Focus)

> Purpose: a practical, code-level reference we’ll use to align our v4 backend (Steps 1–3 + Offer) with official SDK patterns. This doc is intentionally code-heavy, with sections you or Codex Browser can fill from official examples.

## 0) What to look for in official examples
- Agents SDK primitives: sessions/threads, tools registry, guardrails/validation, tracing.
- Chat Completions function calling: JSON-schema tools, tool_choice, tool_call_id handshake, tool role messages.
- Structured outputs: response_format (json_object/json_schema) for extract/classify.
- Multi-agent patterns: router/supervisor, worker agents, specialization, guardrails between agents.
- Parallel tools; background long-running tools; retries/backoff/idempotency.
- Files/retrieval tools; security & scoping.
- ChatKit: actions (buttons/checkboxes), tool result rendering, multi-agent thread UX, approvals/HIL states.

---

## 1) Function/Tool Calling (Chat Completions)
**Pattern**
- Define tools with strict JSON Schema: name, description, parameters (types/enums/required).
- Use `tool_choice` to force/disable tools at gates (don’t rely on prompt only).
- When model returns `tool_calls[]` with ids, respond with `role:"tool"` messages echoing `tool_call_id`. Idempotent handlers dedupe by that id.

**Skeleton**
```python
tools=[{
  "type":"function",
  "function":{
    "name":"rooms_search",
    "description":"Find rooms by date and requirements",
    "parameters":{
      "type":"object",
      "properties":{
        "date":{"type":"string","format":"date"},
        "participants":{"type":"integer","minimum":1},
        "layout":{"type":"string","enum":["theater","u","boardroom"]},
        "special":{"type":"array","items":{"type":"string"}}
      },
      "required":["date","participants"]
    }
  }
}]
tool_choice={"type":"function","function":{"name":"rooms_search"}}
2) Structured Outputs for Classifiers/Extractors
Pattern

Use response_format={"type":"json_object"} or schema-bound variant.

Validate with pydantic/jsonschema; on validation failure → deterministic fallback (regex) or HIL.

Skeleton

python
Copy code
response_format={"type":"json_object"}
# expected keys: {"email","date_ymd","participants","wish_products"}
3) Sessions/State/Guardrails (Agents SDK)
Pattern

Store thread/session with deterministic state (date_confirmed, requirements_hash, caller_step).

Guardrail: validate tool inputs/outputs (server-side); reject/repair before DB.

Tracing hooks for latency/call graph.

Checklist

 Session loader/saver

 Tool I/O validation

 Trace spans around tool calls

4) Multi-Agent Topologies
Patterns observed

Router → specialized workers (intake, calendar/dates, rooms, pricing, offer).

Supervisor merges outputs; guardrails isolate responsibilities.

Skeleton router

python
Copy code
def route(intent):
    if intent in {"intake","email_missing"}: return "intake_agent"
    if intent in {"date_proposal","date_confirm"}: return "dates_agent"
    if intent in {"room_search","room_lock"}: return "rooms_agent"
    if intent in {"compose_offer","special_request"}: return "offer_agent"
    return "fallback_agent"
5) Parallel & Background Tools
Fan-out parallel date checks; deterministic merge ordering.

Background tasks: enqueue, poll status, finalize once.

6) Files/Retrieval
Scoped file handles; redact; cleanup.

Retrieval tools tied to the session/thread.

7) Rate Limits/Idempotency/Retries
Backoff strategy; idempotency keys per tool call; dedupe repeated tool_call_id; surface HIL wait state on persistent errors.

8) ChatKit Integration
Patterns

Render structured tables with action buttons; email-safe deep-link fallback.

Message footer: Step / Next / State consistently (Awaiting Client | Waiting on HIL).

Show which agent spoke for multi-agent UX.

Actions sketch

json
Copy code
{ "type":"action", "name":"select_room", "args":{"room_id":"A101","date":"2025-11-14"} }
9) Quick QoL Upgrades For Us (to consider)
Force tools at gates (date check, room search) with tool_choice.

Convert intake/date/room classifiers to structured outputs (schema validated).

Idempotent tool result handling with tool_call_id.

Light retry wrapper with deterministic idempotency keys.

DEV tracing + structured logs on tool boundaries.

DRY footer injection (already done) — enforce 100% coverage.

10) To-Fill From Official Examples (for Codex Browser)
Paste minimal working snippets for:

Tool definition + call/response handshake

Structured extractor with schema validation

Multi-agent router + worker stubs

Parallel tool fan-out + merge

Background task pattern

ChatKit action wiring end-to-end (server handler + UI)

Include links and commit refs.

yaml
Copy code

---

# 2) One-shot commands to add the doc, commit, push (run in IntelliJ terminal)

```bash
mkdir -p docs/integrations
cat > docs/integrations/openai_agents_sdk_notes.md <<'MD'
# OpenAI Agents SDK & ChatKit — Code Patterns (Multi-Agent Focus)
...paste the markdown from section 1 here...
MD
git add docs/integrations/openai_agents_sdk_notes.md
git commit -m "docs: add OpenAI Agents SDK & ChatKit code-pattern notes (multi-agent focus) for v4"
git push

Tool message handshake (end-to-end, with tool_call_id)
Show the full loop: define tool → model returns tool_calls[] → server executes tool → respond with role:"tool" including the matching tool_call_id (idempotent dedupe).

# 1) Define tool (already in your doc)
tools = [{
  "type":"function",
  "function":{
    "name":"rooms_search",
    "description":"Find rooms by date and requirements",
    "parameters":{
      "type":"object",
      "properties":{
        "date":{"type":"string","format":"date"},
        "participants":{"type":"integer","minimum":1},
        "layout":{"type":"string","enum":["theater","u","boardroom"]},
        "special":{"type":"array","items":{"type":"string"}}
      },
      "required":["date","participants"]
    }
  }
}]

# 2) Force tool usage at the gate
tool_choice = {"type":"function","function":{"name":"rooms_search"}}

# 3) After chat completion returns `tool_calls`
for call in completion.tool_calls:
    if call.function.name == "rooms_search":
        args = json.loads(call.function.arguments)  # validate next!
        res = db.rooms.search(args["date"], args["participants"], args.get("layout"), args.get("special", []))
        # 4) Send tool result message; echo back tool_call_id (idempotent)
        messages.append({
          "role":"tool",
          "tool_call_id": call.id,
          "content": json.dumps({"rooms": res}, ensure_ascii=False)
        })


Structured outputs (schema+validation) for classifiers
Right now you mention response_format=json_object. Add the schema+validation example and a graceful fallback (saves API calls later).

# Ask model for structured output
response_format = {"type":"json_object"}  # or schema-bound variant if available
completion = client.chat.completions.create(
  model=MODEL, messages=messages, response_format=response_format
)
payload = json.loads(completion.choices[0].message.content)

# Validate strictly (pydantic/jsonschema)
class IntakeExtract(BaseModel):
    email: Optional[EmailStr]
    date_ymd: Optional[date]
    participants: Optional[conint(ge=1)]
    wish_products: List[str] = []

try:
    data = IntakeExtract(**payload).model_dump()
except ValidationError:
    # fallback: deterministic parser/regex or ask for clarification (HIL gate if needed)
    data = deterministic_parse(msg_text)


Sessions/state (thread ids) + guardrails
Show session loading/saving and gating validation.

@dataclass
class SessionState:
    thread_id: str
    date_confirmed: bool = False
    requirements_hash: str = ""
    room_eval_hash: str = ""
    caller_step: Optional[str] = None

def load_session(thread_id: str) -> SessionState: ...
def save_session(state: SessionState) -> None: ...

# Guardrail example (server-side)
def validate_tool_args(schema, args):
    jsonschema.validate(args, schema)


Parallel tool fan-out + deterministic merge (e.g., check multiple dates in parallel)

candidates = ["2025-11-14", "2025-11-21", "2025-11-28"]
def check(d): return db.rooms.search(d, participants, layout, special)
results = {d: check(d) for d in candidates}  # replace with async if available
# Deterministic merge: order by input list then tie-break on room name
ordered = [(d, sorted(results[d], key=lambda r: r["name"])) for d in candidates]


Background tasks pattern (long-running tools)
Useful if you later fetch external calendars or pricing.

task_id = enqueue_background("rooms_sync", {"date": date_str})
# Poll or subscribe; keep one finalization message (exactly-once)
while not is_done(task_id):
    sleep(0.5)
final = get_result(task_id)


Retries/backoff + idempotency key
Show a tiny wrapper (prevents duplicates and is testable).

def call_tool_safely(fn, args, idem_key):
    for attempt, delay in [(1,0.2),(2,0.5)]:
        try:
            return fn(**args)
        except TransientError as e:
            if attempt == 2: raise
            time.sleep(delay)


Tracing hooks (DEV)
Even if you don’t wire OpenAI traces yet, add stub spans you can integrate.

with tracer.span("rooms_search") as sp:
    sp.set("date", date_str)
    res = db.rooms.search(date_str, participants, layout, special)


Streaming (optional)
If you later stream assistant text, sketch how to finalize once.

for delta in client.chat.completions.stream(...):
    emit_to_ui(delta)
emit_footer()  # finalize footer once


ChatKit action wiring (server + UI)
You already note action JSON; add the end-to-end handshake.

// UI (ChatKit): send action
sendAction({ type: "select_room", args: { room_id, date } });

// Server handler
if (action.type === "select_room") {
  // Validate args → lock room → respond with a new assistant message + footer
}


Error taxonomy & HIL escalation
Add a short list so behavior is deterministic:

SchemaValidationError → ask client to clarify (Awaiting Client).

TransientToolError → retry; then Waiting on HIL with internal ticket.

PermissionError → immediate HIL escalation.

Timeout when Waiting on HIL → remind client we’re waiting; offer to continue Q&A.

Security/PII & files
Remind: redact emails in logs, scope file ids to session, delete temp files after send.

Testing harness pointers
Note that we already use deterministic TZ/seed; add a “golden transcript” idea for Agents: serialize a few successful tool handshakes as fixtures to prevent regressions



APPENDIX — Future Step: Mixed Providers with ChatKit (OpenAI Agents SDK + LangChain + Mistral)

Goal
Keep v4 workflow and ChatKit UI transport-agnostic while allowing different agents to run on different LLM providers/libraries.

Contracts (MUST NOT change)
- Tools: JSON-schema function tools for all DB/side-effects.
- HIL gates and P1..P4 checks.
- Detours (caller_step), hashes (requirements_hash, room_eval_hash).
- Server handlers return {body_markdown, table_blocks[], actions[], footer}.

Adapters (per agent runtime)
- OpenAI_AgentsSDK_Adapter: uses tool_choice + json_schema structured outputs; dedupe by tool_call_id.
- LangChain_Adapter: wraps existing chains/tools; emits same structured outputs; generates idempotency_key.
- Mistral_Adapter: direct or via LangChain Runnable; same contracts.

Router (per step/intent → adapter)
- intake/date → OpenAI_AgentsSDK_Adapter
- room → LangChain_Adapter
- offer/nego → provider by env (openai|langchain|mistral)

Transport
- ChatKit: render actions; post action payload to server handler → adapter → tools → reply with footer.
- Email: deep-link tokens to the same handlers; reply parser fallback.

Determinism
- TZ=Europe/Zurich; RNG seed.
- Adapter selection must not change mid-thread unless explicitly configured.

Tests to enforce
- Same state transitions through ChatKit actions regardless of adapter.
- Tool I/O schemas validated identically for all adapters.
- No gate skipping across providers; HIL approvals enforced.
- Idempotency: retrying an action does not duplicate side-effects.

Config switches
AGENT_INTAKE_PROVIDER=openai
AGENT_DATES_PROVIDER=openai
AGENT_ROOMS_PROVIDER=langchain
AGENT_OFFER_PROVIDER=mistral
