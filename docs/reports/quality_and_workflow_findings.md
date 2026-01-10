1) Executive Summary
Overall quality risk rating: High
Top 10 quality risks (titles only):
1. Process-local conversation state drops sessions on restart/multi-worker
2. JSON DB updates are not atomic across concurrent requests
3. Tenant-unaware config/site-visit/confirmation reads shared DB path
4. Out-of-context and nonsense handling returns empty responses
5. Empty-reply guard injects generic fallbacks and masks workflow gaps
6. ENV default mismatch exposes debug info inconsistently
7. Request handlers mutate AGENT_MODE globally, overriding provider config
8. Auth disabled by default and JWT mode is stubbed
9. Unified detection fallback returns generic intent on LLM errors
10. Missing thread_id validation collapses distinct conversations
Vibecode risk estimate: Medium

2) Quality Rubric (table)
| Area | Score (1-5) | Justification |
| --- | --- | --- |
| Domain modeling & boundaries | 3 | - Workflow types and state objects are defined and reused.<br>- Multiple layers still reach into shared DB files and globals directly. |
| Workflow/state-machine correctness | 3 | - Structured steps and routing loop exist with guards and detours.<br>- Several special-case patches and silent ignores indicate fragile edges. |
| Error handling & failure modes | 2 | - Many failures are converted into generic fallbacks or silence.<br>- Missing thread/session validation can hard-fail user requests. |
| Determinism & LLM integration safety | 2 | - LLM JSON parsing falls back to generic results on errors.<br>- Provider selection can be altered by request-time env mutation. |
| API/UX contract quality | 2 | - Some inputs intentionally yield empty responses.<br>- Session continuity depends on process-local memory. |
| Test strategy & regression resistance | 3 | - Dedicated test suites exist across flow/regression/unit/smoke.<br>- No visible concurrency or multi-worker validation in inspected code. |
| Observability & debuggability | 3 | - Trace hooks and fallback diagnostics exist in several layers.<br>- Silent ignore paths reduce visibility to end users. |
| Config hygiene (defaults, toggles, env separation) | 2 | - ENV defaults differ by module (prod vs dev).<br>- Auth and provider modes default to permissive or implicit states. |

3) Coverage
Repo map (short):
- `atelier-ai-frontend/` Next.js UI and chat tooling
- `api/` FastAPI routes and middleware
- `workflows/` workflow engine, steps, runtime routing, IO
- `workflow/` guards and workflow helpers
- `detection/` intent/entity detection logic
- `llm/` provider config and adapters
- `legacy/` in-memory session store and caches
- `agents/` agent orchestration and runner
- `chatkit/` ChatKit server integration
- `core/` fallback and safety utilities
- `utils/` shared helpers
- `tests/` regression/unit/flow suites

Top 15 high-leverage files reviewed first:
- `main.py`
- `workflow_email.py`
- `api/routes/messages.py`
- `api/routes/tasks.py`
- `api/routes/events.py`
- `api/routes/config.py`
- `api/middleware/auth.py`
- `api/middleware/tenant_context.py`
- `workflows/runtime/pre_route.py`
- `workflows/runtime/router.py`
- `workflows/io/database.py`
- `workflows/io/config_store.py`
- `detection/unified.py`
- `workflows/common/site_visit_handler.py`
- `legacy/session_store.py`

Commands executed (exact commands) and outcomes:
- `ls` -> listed repository root contents.
- `ls reports` -> error: no such directory.
- `ls backend` -> listed JSON data files and tmp-cache.
- `sed -n '1,200p' README.md` -> reviewed repo overview and architecture.
- `sed -n '1,260p' main.py` -> reviewed app startup logic and middleware wiring.
- `sed -n '260,520p' main.py` -> reviewed dev auto-launch/port logic.
- `sed -n '520,1040p' main.py` -> reviewed __main__ startup path.
- `sed -n '1,260p' workflow_email.py` -> reviewed workflow orchestration and DB path handling.
- `sed -n '260,620p' workflow_email.py` -> reviewed routing and pre-route pipeline wiring.
- `sed -n '620,1080p' workflow_email.py` -> reviewed output finalization and HIL logic.
- `ls workflows` -> listed workflow engine modules.
- `ls atelier-ai-frontend` -> listed frontend app structure.
- `ls atelier-ai-frontend/app` -> listed app routes/components.
- `ls atelier-ai-frontend/app/agent` -> confirmed agent page.
- `ls atelier-ai-frontend/app/admin` -> confirmed admin subtree.
- `ls api` -> listed API package layout.
- `ls api/routes` -> listed API route modules.
- `sed -n '1,260p' api/routes/messages.py` -> reviewed conversation endpoints and fallbacks.
- `sed -n '260,620p' api/routes/messages.py` -> reviewed date confirmation and workflow integration.
- `sed -n '620,1220p' api/routes/messages.py` -> reviewed send-message flow and silent actions.
- `sed -n '1,280p' workflows/runtime/router.py` -> reviewed step routing loop.
- `sed -n '1,320p' workflows/runtime/pre_route.py` -> reviewed pre-route logic and out-of-context handling.
- `sed -n '320,720p' workflows/runtime/pre_route.py` -> reviewed escalation and billing step correction.
- `sed -n '1,260p' workflows/io/database.py` -> reviewed file lock and DB load behavior.
- `sed -n '260,620p' workflows/io/database.py` -> reviewed DB update helpers and defaults.
- `ls llm` -> listed LLM provider modules.
- `sed -n '1,260p' llm/provider_config.py` -> reviewed provider selection and hybrid enforcement.
- `sed -n '260,620p' llm/provider_config.py` -> reviewed validation output behavior.
- `sed -n '1,260p' llm/provider_registry.py` -> reviewed provider cache logic.
- `sed -n '1,260p' workflows/llm/adapter.py` -> reviewed LLM adapter and caching.
- `sed -n '1,240p' core/fallback.py` -> reviewed fallback diagnostics.
- `sed -n '1,260p' workflows/common/site_visit_handler.py` -> reviewed site visit flow start logic.
- `sed -n '260,620p' workflows/common/site_visit_handler.py` -> reviewed site visit date selection and conflict logic.
- `sed -n '1,260p' workflows/io/config_store.py` -> reviewed config DB access defaults.
- `sed -n '1,260p' api/middleware/__init__.py` -> reviewed middleware exports.
- `sed -n '1,260p' api/middleware/tenant_context.py` -> reviewed tenant header context.
- `sed -n '1,260p' api/middleware/auth.py` -> reviewed auth toggles and JWT placeholder.
- `sed -n '1,260p' workflows/io/tasks.py` -> reviewed task queue storage.
- `sed -n '1,260p' detection/unified.py` -> reviewed unified detection prompt and parse.
- `sed -n '260,620p' detection/unified.py` -> reviewed fallback behavior on LLM errors.
- `sed -n '1,260p' workflow/guards.py` -> reviewed guard evaluation logic.
- `sed -n '1,260p' legacy/session_store.py` -> reviewed in-memory session store.
- `sed -n '1,260p' api/routes/tasks.py` -> reviewed HIL task endpoints.
- `sed -n '1,260p' api/routes/config.py` -> reviewed config endpoints.
- `sed -n '1,260p' api/routes/workflow.py` -> reviewed workflow health endpoint.
- `sed -n '1,260p' api/routes/events.py` -> reviewed deposit endpoints.
- `sed -n '1,260p' workflows/steps/step1_intake/__init__.py` -> reviewed intake step exports.
- `sed -n '1,260p' workflows/steps/step1_intake/trigger/process.py` -> reviewed intake trigger wiring.
- `sed -n '1,260p' workflows/steps/step1_intake/trigger/step1_handler.py` -> reviewed intake logic and heuristics.
- `sed -n '1,240p' workflows/common/types.py` -> reviewed workflow state model.
- `sed -n '1,260p' atelier-ai-frontend/app/agent/page.tsx` -> reviewed agent chat UI behavior.
- `sed -n '1,200p' atelier-ai-frontend/app/page.tsx` -> reviewed main chat UI behavior.
- `sed -n '1,260p' api/agent_router.py` -> reviewed agent/chatkit endpoints.
- `sed -n '1,260p' chatkit/server.py` -> reviewed chatkit request mapping.
- `sed -n '1,240p' agents/openevent_agent.py` -> reviewed agent fallback behavior.
- `rg -n "nonsense_ignored"` -> found silent ignore cases in step handlers and messages route.
- `sed -n '300,420p' workflows/steps/step2_date_confirmation/trigger/step2_handler.py` -> reviewed nonsense gate behavior.
- `rg -n "events_database\\.json"` -> found default DB path usage across modules.
- `sed -n '1,200p' workflows/common/confirmation_gate.py` -> reviewed confirmation gate DB reload.
- `rg -n "clear_provider_cache"` -> found LLM provider cache invalidation.
- `rg -n "active_conversations"` -> found session store usage across routes.
- `nl -ba legacy/session_store.py | sed -n '80,140p'` -> collected line references for in-memory session store.
- `nl -ba api/routes/messages.py | sed -n '630,740p'` -> collected line references for session lookup.
- `nl -ba api/routes/messages.py | sed -n '520,610p'` -> collected line references for session storage.
- `nl -ba workflows/io/config_store.py | sed -n '1,80p'` -> collected line references for static config DB path.
- `nl -ba workflows/common/site_visit_handler.py | sed -n '40,120p'` -> collected line references for default DB path.
- `nl -ba workflows/common/confirmation_gate.py | sed -n '110,190p'` -> collected line references for default DB path.
- `nl -ba workflows/runtime/pre_route.py | sed -n '140,260p'` -> collected line references for out-of-context logic.
- `nl -ba workflows/runtime/pre_route.py | sed -n '260,340p'` -> collected line references for out-of-context responses.
- `nl -ba workflows/steps/step2_date_confirmation/trigger/step2_handler.py | sed -n '340,400p'` -> collected line references for nonsense gate.
- `nl -ba api/routes/messages.py | sed -n '740,820p'` -> collected line references for silent responses.
- `nl -ba workflow_email.py | sed -n '330,460p'` -> collected line references for process_msg and empty reply guard.
- `nl -ba workflow_email.py | sed -n '460,560p'` -> collected line references for empty reply fallback details.
- `nl -ba detection/unified.py | sed -n '230,340p'` -> collected line references for LLM parsing.
- `nl -ba detection/unified.py | sed -n '340,420p'` -> collected line references for LLM fallback.
- `nl -ba workflows/io/database.py | sed -n '90,180p'` -> collected line references for file lock.
- `nl -ba workflows/io/database.py | sed -n '180,260p'` -> collected line references for load/save locking scope.
- `nl -ba api/middleware/auth.py | sed -n '1,120p'` -> collected line references for auth defaults and JWT stub.
- `rg -n "AGENT_MODE" api/routes/messages.py` -> found env mutation points.
- `nl -ba api/routes/messages.py | sed -n '360,390p'` -> collected line references for AGENT_MODE setdefault.
- `nl -ba api/routes/messages.py | sed -n '440,480p'` -> collected line references for start_conversation AGENT_MODE setdefault.
- `nl -ba atelier-ai-frontend/app/agent/page.tsx | sed -n '110,210p'` -> collected line references for ChatKit secret fallback.
- `nl -ba api/routes/workflow.py | sed -n '1,80p'` -> collected line references for ENV default in workflow routes.
- `nl -ba main.py | sed -n '20,80p'` -> collected line references for ENV default in app entry.

Tests/lints/typechecks: Not run.

4) Findings Index (table)
| ID | Severity | Type | Area | Title | Location | Confidence | Verified? |
| --- | --- | --- | --- | --- | --- | --- | --- |
| F-01 | High | Operational blind spot | Reliability | Process-local session store drops conversations on restart/multi-worker | `legacy/session_store.py:100-105`; `api/routes/messages.py:646-649` | High | Yes |
| F-02 | High | Non-determinism | Reliability | JSON DB load/save is not atomic across concurrent requests | `workflow_email.py:367-370`; `workflow_email.py:343-347`; `workflows/io/database.py:188-190` | Medium | Yes |
| F-03 | High | Fragile coupling | Reliability | Tenant-unaware config and site-visit flows read shared DB path | `workflows/io/config_store.py:22-24`; `workflows/common/site_visit_handler.py:56-77`; `workflows/common/confirmation_gate.py:127-129` | High | Yes |
| F-04 | Medium | UX/API sharp edge | UX-API | Out-of-context and nonsense handling returns empty responses | `workflows/runtime/pre_route.py:154-268`; `workflows/steps/step2_date_confirmation/trigger/step2_handler.py:357-364`; `api/routes/messages.py:754-767` | High | Yes |
| F-05 | Medium | Symptom patch | Workflow | Empty-reply guard injects generic fallbacks | `workflow_email.py:432-472` | High | Yes |
| F-06 | Medium | Hardcoded heuristic | Observability | ENV default mismatch exposes debug info inconsistently | `main.py:49-54`; `api/routes/workflow.py:21-33` | High | Yes |
| F-07 | Medium | Hardcoded heuristic | LLM | Request handlers mutate AGENT_MODE globally | `api/routes/messages.py:372-374`; `api/routes/messages.py:463-464` | High | Yes |
| F-08 | Medium | Operational blind spot | Security | Auth disabled by default; JWT mode is stubbed | `api/middleware/auth.py:8-14`; `api/middleware/auth.py:94-118` | High | Yes |
| F-09 | Medium | Non-determinism | LLM | Unified detection falls back to generic intent on LLM errors | `detection/unified.py:297-350`; `detection/unified.py:351-392` | Medium | Yes |
| F-10 | Medium | Missing validation | Reliability | Missing thread_id validation collapses distinct conversations | `workflow_email.py:374-381` | Medium | Yes |

5) Detailed Findings

### F-01 - Process-local session store drops conversations on restart/multi-worker
- ID: F-01
- Title: Process-local session store drops conversations on restart/multi-worker
- Severity: High
- Type: Operational blind spot
- Area: Reliability
- Confidence: High

Evidence:
- `legacy/session_store.py:100-105`
```
# In-memory storage with TTL for session cleanup
active_conversations: dict[str, ConversationState] = _TTLDict()
STEP3_DRAFT_CACHE: Dict[str, str] = {}
STEP3_PAYLOAD_CACHE: Dict[str, Dict[str, Any]] = {}
```
- `api/routes/messages.py:646-649`
```
if request.session_id not in active_conversations:
    raise HTTPException(status_code=404, detail="Conversation not found")
conversation_state = active_conversations[request.session_id]
```

Behavioral impact:
- User: after a process restart or a request routed to a different worker, session_id requests return 404 and conversation history is lost.
- Ops: incident response is opaque because state is in memory, not in the persisted DB.
- Concurrency/restarts/multi-worker: non-sticky load balancing breaks session continuity; caches do not survive restarts.

Why this is symptom vs cause (if applicable): Not a symptom patch; this is a core state-management choice.

Assumptions and what evidence is missing: Assumes non-sticky routing or restarts, which are common in production deployments.

### F-02 - JSON DB load/save is not atomic across concurrent requests
- ID: F-02
- Title: JSON DB load/save is not atomic across concurrent requests
- Severity: High
- Type: Non-determinism
- Area: Reliability
- Confidence: Medium

Evidence:
- `workflow_email.py:367-370`
```
path = _resolve_tenant_db_path(Path(db_path))
lock_path = _resolve_lock_path(path)
db = db_io.load_db(path, lock_path=lock_path)
```
- `workflow_email.py:343-347`
```
if state.extras.pop("_pending_save", False):
    db_io.save_db(state.db, path, lock_path=lock_path)
```
- `workflows/io/database.py:188-190`
```
with FileLock(lock_candidate):
    db = _do_load()
```

Behavioral impact:
- User: concurrent messages can overwrite each other, leading to missing updates or inconsistent step state.
- Ops: hard-to-reproduce incidents from last-write-wins behavior and nondeterministic state.
- Concurrency/restarts/multi-worker: separate processes load the same snapshot, process independently, and overwrite each other on save.

Why this is symptom vs cause (if applicable): Root-cause gap in transaction scope; lock only wraps I/O, not the processing window.

Assumptions and what evidence is missing: Assumes concurrent message processing against the same DB file, which is likely in multi-worker setups.

### F-03 - Tenant-unaware config and site-visit flows read shared DB path
- ID: F-03
- Title: Tenant-unaware config and site-visit flows read shared DB path
- Severity: High
- Type: Fragile coupling
- Area: Reliability
- Confidence: High

Evidence:
- `workflows/io/config_store.py:22-24`
```
# Database path (same as workflow_email.py)
DB_PATH = Path(__file__).resolve().parents[2] / "events_database.json"
```
- `workflows/common/site_visit_handler.py:56-77`
```
_DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "events_database.json"
...
return load_db(_DEFAULT_DB_PATH)
```
- `workflows/common/confirmation_gate.py:127-129`
```
default_path = Path(__file__).resolve().parents[2] / "events_database.json"
path = db_path or default_path
db = load_db(path)
```

Behavioral impact:
- User: site-visit conflicts and venue settings can be pulled from the wrong tenant, producing incorrect availability or messaging.
- Ops: cross-tenant data contamination risks if tenant headers are enabled.
- Concurrency/restarts/multi-worker: per-tenant DB files and shared config reads drift apart, causing inconsistent behavior per request.

Why this is symptom vs cause (if applicable): Hardcoded coupling to a single DB file sidesteps the tenant-aware path used elsewhere.

Assumptions and what evidence is missing: Assumes TENANT_HEADER_ENABLED or OE_TEAM_ID is used to route data for multi-tenant mode.

### F-04 - Out-of-context and nonsense handling returns empty responses
- ID: F-04
- Title: Out-of-context and nonsense handling returns empty responses
- Severity: Medium
- Type: UX/API sharp edge
- Area: UX-API
- Confidence: High

Evidence:
- `workflows/runtime/pre_route.py:154-268`
```
# Out-of-context messages should receive NO response
...
ooc_response = GroupResult(
    action="out_of_context_ignored",
    halt=True,
    payload={...},
)
```
- `workflows/steps/step2_date_confirmation/trigger/step2_handler.py:357-364`
```
if nonsense_action == "ignore":
    return GroupResult(
        action="nonsense_ignored",
        payload={...},
        halt=True,
    )
```
- `api/routes/messages.py:754-767`
```
silent_actions = {"out_of_context_ignored", "nonsense_ignored"}
if workflow_action in silent_actions:
    return {..., "response": "", ...}
```

Behavioral impact:
- User: client sees no reply for valid but mistimed actions, which appears like a system outage.
- Ops: support teams receive vague reports with no visible error message or clue.
- Concurrency/restarts/multi-worker: repeated retries can flood logs without resolving the user path.

Why this is symptom vs cause (if applicable): Hardcoded response suppression is used instead of explicit user guidance.

Assumptions and what evidence is missing: Assumes UI surfaces empty responses as silence; frontend behavior depends on how empty responses are rendered.

### F-05 - Empty-reply guard injects generic fallbacks
- ID: F-05
- Title: Empty-reply guard injects generic fallbacks
- Severity: Medium
- Type: Symptom patch
- Area: Workflow
- Confidence: High

Evidence:
- `workflow_email.py:432-472`
```
if not state.draft_messages:
    logger.warning("[WF][EMPTY_REPLY_GUARD] No draft messages after routing loop!")
    ...
    fallback_draft = {
        "body_markdown": fallback_body,
        "topic": "empty_reply_fallback",
    }
    state.add_draft_message(fallback_draft)
```

Behavioral impact:
- User: receives a generic "processing" message even when the workflow failed to produce a valid reply.
- Ops: underlying workflow gaps are masked, making root-cause analysis harder.
- Concurrency/restarts/multi-worker: failures can look like successful responses, delaying detection.

Why this is symptom vs cause (if applicable): This is explicitly labeled as a safety-net fix rather than addressing the missing draft root cause.

Assumptions and what evidence is missing: Assumes upstream steps can fail to add drafts, which is implied by the guard.

### F-06 - ENV default mismatch exposes debug info inconsistently
- ID: F-06
- Title: ENV default mismatch exposes debug info inconsistently
- Severity: Medium
- Type: Hardcoded heuristic
- Area: Observability
- Confidence: High

Evidence:
- `main.py:49-54`
```
_env_value = os.getenv("ENV", "prod").lower()
_IS_DEV = _env_value in ("dev", "development", "local")
```
- `api/routes/workflow.py:21-33`
```
_IS_DEV = os.getenv("ENV", "dev").lower() != "prod"
...
if _IS_DEV:
    return {"db_path": str(WF_DB_PATH), "ok": True}
```

Behavioral impact:
- User: environment-dependent responses differ across endpoints in the same process.
- Ops: DB path disclosure can occur when ENV is unset, even if the main app treats it as prod.
- Concurrency/restarts/multi-worker: inconsistent defaults complicate environment verification.

Why this is symptom vs cause (if applicable): Hardcoded module-local defaults create divergent behavior.

Assumptions and what evidence is missing: Assumes ENV is unset or inconsistently configured across deployments.

### F-07 - Request handlers mutate AGENT_MODE globally
- ID: F-07
- Title: Request handlers mutate AGENT_MODE globally
- Severity: Medium
- Type: Hardcoded heuristic
- Area: LLM
- Confidence: High

Evidence:
- `api/routes/messages.py:372-374`
```
os.environ.setdefault("AGENT_MODE", "openai")
synthetic_msg = {
```
- `api/routes/messages.py:463-464`
```
os.environ.setdefault("AGENT_MODE", "openai")
subject_line = (...)
```

Behavioral impact:
- User: provider selection can flip to single-provider mode after first request, changing behavior mid-run.
- Ops: runtime LLM routing differs from configuration, making deployments hard to reason about.
- Concurrency/restarts/multi-worker: the first request in a process can set a global default for all subsequent requests.

Why this is symptom vs cause (if applicable): A request-time env mutation is used to guarantee a provider, rather than being an explicit config layer.

Assumptions and what evidence is missing: Assumes AGENT_MODE is not already set in the environment.

### F-08 - Auth disabled by default; JWT mode is stubbed
- ID: F-08
- Title: Auth disabled by default; JWT mode is stubbed
- Severity: Medium
- Type: Operational blind spot
- Area: Security
- Confidence: High

Evidence:
- `api/middleware/auth.py:8-14`
```
Default: AUTH_ENABLED=0 (no auth checks - dev/test behavior unchanged)
```
- `api/middleware/auth.py:94-118`
```
# TODO Phase 3: Implement JWT validation
# For now, return not implemented
...
return False, "supabase_jwt_not_implemented", {}
```

Behavioral impact:
- User: production deployments can be unintentionally open without explicit toggles.
- Ops: authentication posture depends on env configuration rather than enforced defaults.
- Concurrency/restarts/multi-worker: all workers share the same permissive default unless configured.

Why this is symptom vs cause (if applicable): This is a configuration default and stubbed path rather than a runtime error.

Assumptions and what evidence is missing: Assumes AUTH_ENABLED is not set in production and that JWT mode may be selected.

### F-09 - Unified detection falls back to generic intent on LLM errors
- ID: F-09
- Title: Unified detection falls back to generic intent on LLM errors
- Severity: Medium
- Type: Non-determinism
- Area: LLM
- Confidence: Medium

Evidence:
- `detection/unified.py:297-350`
```
except json.JSONDecodeError as e:
    ...
    return UnifiedDetectionResult(
        intent="general_qna",
        intent_confidence=0.3,
    )
```
- `detection/unified.py:351-392`
```
except Exception as e:
    ...
    return UnifiedDetectionResult(
        intent="general_qna",
        intent_confidence=0.3,
    )
```

Behavioral impact:
- User: messages can be misrouted to general QnA flows after transient LLM issues.
- Ops: intermittent LLM formatting errors manifest as workflow misclassification rather than explicit failure.
- Concurrency/restarts/multi-worker: fallback behavior varies by provider failure timing, leading to nondeterministic outcomes.

Why this is symptom vs cause (if applicable): Error handling defaults to a generic intent rather than validating or rejecting the result.

Assumptions and what evidence is missing: Assumes LLM output occasionally fails JSON parsing or returns partial fields.

### F-10 - Missing thread_id validation collapses distinct conversations
- ID: F-10
- Title: Missing thread_id validation collapses distinct conversations
- Severity: Medium
- Type: Missing validation
- Area: Reliability
- Confidence: Medium

Evidence:
- `workflow_email.py:374-381`
```
raw_thread_id = (
    msg.get("thread_id")
    or msg.get("thread")
    or msg.get("session_id")
    or msg.get("msg_id")
    or msg.get("from_email")
    or "unknown-thread"
)
```

Behavioral impact:
- User: separate requests without explicit thread_id can be merged into a single workflow state.
- Ops: debugging becomes difficult when unrelated events share the same thread identifier.
- Concurrency/restarts/multi-worker: collisions are more likely with partial payloads from external integrations.

Why this is symptom vs cause (if applicable): This is a fallback path that accepts missing identifiers instead of validating input.

Assumptions and what evidence is missing: Assumes some callers omit thread_id/session_id or provide inconsistent IDs.

6) Real-world scenario probes (8-12 items)
1) Scenario description: Client starts a conversation, server restarts, then the client sends a follow-up message using the same session_id.
Expected behavior (production-grade): Session resumes with prior context and workflow state.
Observed/likely behavior based on code evidence: 404 Conversation not found because session state is process-local in `active_conversations` (F-01).
Related finding IDs: F-01.

2) Scenario description: Two messages arrive nearly simultaneously for the same event on different workers.
Expected behavior (production-grade): Updates are serialized or merged without data loss.
Observed/likely behavior based on code evidence: Both workers load the same DB snapshot and the later save overwrites earlier changes (F-02).
Related finding IDs: F-02.

3) Scenario description: Two tenants operate concurrently, each with different site-visit blocked dates.
Expected behavior (production-grade): Tenant A and B remain isolated in config and scheduling.
Observed/likely behavior based on code evidence: Site-visit and config modules read the shared `events_database.json` path, mixing tenant state (F-03).
Related finding IDs: F-03.

4) Scenario description: Client sends "I accept the offer" while still at date-confirmation step.
Expected behavior (production-grade): System replies with guidance about the correct step.
Observed/likely behavior based on code evidence: Message is classified as out-of-context and returns an empty response (F-04).
Related finding IDs: F-04.

5) Scenario description: Client message is borderline nonsense or low confidence at Step 2.
Expected behavior (production-grade): Clear error or clarification prompt is returned.
Observed/likely behavior based on code evidence: The flow can return no response (nonsense_ignored) or a manager-only path with no client feedback (F-04).
Related finding IDs: F-04.

6) Scenario description: Workflow routing completes but no draft message is produced due to an internal gap.
Expected behavior (production-grade): A visible error state with explicit next action.
Observed/likely behavior based on code evidence: Empty-reply guard injects a generic "processing" message, masking the underlying failure (F-05).
Related finding IDs: F-05.

7) Scenario description: ENV is unset in deployment, and /api/workflow/health is called.
Expected behavior (production-grade): Consistent prod defaults and no debug detail leakage.
Observed/likely behavior based on code evidence: main app defaults to prod, but workflow route defaults to dev and returns db_path (F-06).
Related finding IDs: F-06.

8) Scenario description: Deployment expects hybrid LLM routing but AGENT_MODE is not set in the environment.
Expected behavior (production-grade): Provider selection follows configured hybrid defaults.
Observed/likely behavior based on code evidence: First start_conversation or confirm_date request sets AGENT_MODE to openai, forcing single-provider behavior (F-07).
Related finding IDs: F-07.

9) Scenario description: LLM returns malformed JSON during unified detection.
Expected behavior (production-grade): Deterministic fallback with explicit user-facing error or safe classification.
Observed/likely behavior based on code evidence: Fallback returns generic intent=general_qna with low confidence, which can misroute or suppress responses (F-09, F-04).
Related finding IDs: F-09, F-04.

10) Scenario description: An integration posts to the workflow without thread_id or session_id.
Expected behavior (production-grade): Request is rejected or a new thread is created explicitly.
Observed/likely behavior based on code evidence: Fallback to msg_id/from_email or "unknown-thread" collapses unrelated conversations (F-10).
Related finding IDs: F-10.
