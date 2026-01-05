# Agent Skills Plan — OpenEvent-AI (Codex + Claude Code)

**Date:** 2025-12-28  
**Goal:** Standardize repeatable agent workflows for refactoring, bug triage, and E2E verification (especially the site-visit path), so Codex / Claude Code / Gemini can debug fast and produce production-grade changes.

This plan defines a **shared set of project skills** implemented twice:
- **Codex skills:** `.codex/skills/<skill>/SKILL.md`
- **Claude Code skills:** `.claude/skills/<skill>/SKILL.md`

Each skill has the **same name + description + workflow**, so agents behave consistently across tools.

---

## Skill Set (Proposed + Implemented)

### 1) `oe-e2e-site-visit`
**Purpose:** Deterministically reach and verify the Step 7 site-visit flow (including the “site visit options” message), with a fast backend-only lane and an optional browser lane.

**Primary triggers:** “E2E”, “Playwright”, “site visit”, “Step 7”, “confirm booking”, “UI validation”.

**Key repo assets used:**
- `scripts/manual_ux/manual_ux_scenario_I.py` (site visit flow)
- `scripts/manual_ux/manual_ux_scenario_H.py` (site visit + later change)
- `scripts/manual_ux/validate_manual_ux_run.py` (trace validator)
- `scripts/dev/dev_server.sh` (backend dev server)

**Optional tool/MCP dependencies:**
- Playwright MCP (`@playwright/mcp`) for browser driving.

---

### 2) `oe-lsp-pyright-refactor`
**Purpose:** Use LSP/Pyright-driven semantic analysis to plan refactors safely (definitions/references/renames/diagnostics) and keep refactor PRs “shim-first”.

**Primary triggers:** “refactor”, “rename symbol”, “find references”, “pyright errors”, “type contracts”, “LSP”.

**Key repo assets used:**
- `docs/internal/backend/BACKEND_REFACTORING_PLAN_DEC_2025.md`
- `docs/internal/backend/BACKEND_REFACTORING_PLAN_DEC_2025_ADDENDUM.md`

**Tooling dependencies:**
- LSP MCP server (Pyright LSP under MCP).

---

### 3) `oe-backend-prod-hardening`
**Purpose:** Run a focused “production hygiene” review and produce actionable fixes (no drive-by changes): logging, error handling, fallback leakage, dev-only defaults.

**Primary triggers:** “production ready”, “LLM smells”, “prints”, “except pass”, “fallback diagnostics”, “dangerous endpoints”.

**Key repo assets used:**
- `docs/internal/backend/BACKEND_REFACTORING_PLAN_DEC_2025_ADDENDUM.md`

---

### 4) `oe-workflow-triage`
**Purpose:** Turn a bug report (stack trace, wrong behavior, bad message) into a minimal reproduction script/trace and a tight fix plan tied to workflow invariants.

**Primary triggers:** “bug”, “regression”, “repro”, “workflow broke”, “wrong step”, “detour”, “HIL”.

**Key repo assets used:**
- `scripts/manual_ux_scenario_*.py` (deterministic stubs)
- `scripts/manual_ux/validate_manual_ux_run.py`
- `tests/specs/*` and `backend/tests/*` (characterization-first)

---

### 5) `oe-mcp-bootstrap`
**Purpose:** Standardize how contributors set up MCP servers (filesystem, context7, LSP/Pyright, Playwright) and keep secrets out of the repo.

**Primary triggers:** “setup MCP”, “configure codex”, “configure claude”, “Context7”, “Playwright MCP”, “LSP MCP”.

---

### 6) `oe-docs-updates`
**Purpose:** Keep the “living docs” accurate as the code evolves: document bug status and regression tests in the Team Guide; record shipped behavior changes in the changelog; park future ideas in `new_features.md`.

**Primary triggers:** “update TEAM_GUIDE”, “document bug”, “known issue”, “add to changelog”, “new feature idea”, “update TODO”.

**Docs updated by this skill:**
- `docs/guides/TEAM_GUIDE.md`
- `DEV_CHANGELOG.md`
- `new_features.md`
- `TO_DO_NEXT_SESS.md`

---

### 7) `oe-release-readiness`
**Purpose:** Standard “ship gate” checklist (fast lanes first) to ensure PRs are production-ready, agent-debuggable, and don’t regress the Step 1–7 workflow.

**Primary triggers:** “ready to ship”, “pre-merge checks”, “release readiness”, “CI gate”.

**Key repo assets used:**
- `scripts/tests/test-smoke.sh` (fast smoke lane)
- `scripts/tests/test-all.sh` (full suite)
- `scripts/tests/verify_refactor.py` (compile/import sanity + refactor invariants)
- `scripts/manual_ux/manual_ux_scenario_I.py` + `scripts/manual_ux/validate_manual_ux_run.py` (site-visit trace contract)

---

### 8) `oe-trace-and-fallback-triage`
**Purpose:** Turn “we got a fallback / generic stub / empty reply” into a precise root-cause path with minimal repro traces and clear next actions.

**Primary triggers:** “fallback”, “empty reply”, “Thanks for your message…” stub, “no specific information available”, “diagnostics”.

**Key repo assets used:**
- `docs/guides/TEAM_GUIDE.md` (“Fallback Diagnostic System” + known failure chains)
- `backend/workflows/common/fallback_reason.py` (workflow fallback reasons)
- `scripts/manual_ux_scenario_*.py` + `scripts/manual_ux/validate_manual_ux_run.py` (deterministic repro lane)

---

### 9) `oe-integration-mode-smoke`
**Purpose:** Quick, reliable smoke checks for “real integrations” (Supabase + live OpenAI integration tests) without turning every dev session into a production deployment.

**Primary triggers:** “integration mode”, “supabase”, “live OpenAI tests”, “why does prod differ”, “connection test”.

**Key repo assets used:**
- `backend/workflows/io/integration/test_connection.py` (Supabase config/connection validator)
- `backend/tests_integration/` (live OpenAI e2e/integration lane)

---

### 10) `oe-security-prompt-injection`
**Purpose:** Keep prompt-injection defenses regression-tested and easy to extend when new attacks are observed.

**Primary triggers:** “prompt injection”, “security regression”, “malicious input”, “system prompt leak”.

**Key repo assets used:**
- `backend/tests/regression/test_security_prompt_injection.py`

---

### 11) `oe-backend-startup-triage`
**Purpose:** Fix “backend won’t start / first request 500 / port stuck” quickly and consistently (ports, bytecode cache, env).

**Primary triggers:** “backend won’t start”, “uvicorn reload weirdness”, “unexpected keyword argument”, “port 8000/3000”, “stuck loading”.

**Key repo assets used:**
- `scripts/dev/dev_server.sh` (canonical dev start/stop with port cleanup + key loading)
- `docs/guides/TEAM_GUIDE.md` (“Python Bytecode Cache Causing Startup Failures”, “Frontend zombie process”)
- `README.md` (local run instructions)

---

### 12) `oe-hil-and-billing-triage`
**Purpose:** Debug “manager tasks missing / approve button fails / billing+deposit flow stuck” with a concrete checklist and targeted tests.

**Primary triggers:** “HIL task missing”, “manager tasks panel empty”, “approve button fails”, “billing not persisted”, “deposit paid but stuck”.

**Key repo assets used:**
- `docs/guides/TEAM_GUIDE.md` (HIL + billing/deposit regressions and playbooks)
- `backend/tests/agents/test_manager_approve_path.py` (approve/reject path)
- `tests/specs/gatekeeping/test_hil_gates.py` (gatekeeping invariants)

---

### 13) `oe-test-matrix-navigator`
**Purpose:** Choose the smallest high-signal test subset from the test matrix based on what changed (detection vs flow vs regression), so agents can reproduce and fix bugs faster.

**Primary triggers:** “what tests should I run”, “test subset”, “DET_”, “FLOW_”, “REG_”, “matrix”.

**Key repo assets used:**
- `tests/TEST_MATRIX_detection_and_flow.md` (canonical test IDs + scenarios)
- `tests/TEST_INVENTORY.md` (where tests live + current fail/pass status)
- `scripts/tests/test-smoke.sh` (fast baseline)

---

### 14) `oe-project-orientation`
**Purpose:** Quick repo navigation when an agent/dev is “lost”: point to the most important docs, entrypoints, scripts, and where to debug each workflow step.

**Primary triggers:** “overview”, “where is …”, “I’m lost”, “how is this repo organized”, “what docs matter”.

**Key repo assets used:**
- `README.md` (architecture + how to run)
- `docs/guides/TEAM_GUIDE.md` (workflow contracts + known regressions + playbooks)
- `docs/internal/*` (refactor plans + code review findings)
- `tests/TEST_INVENTORY.md` + `tests/TEST_MATRIX_detection_and_flow.md` (test navigation)
- `scripts/*` (dev server + deterministic UX scenarios)

---

## Installation / Scope Policy

**Repo-shared skills (committed):**
- `.codex/skills/*` and `.claude/skills/*`

**User-local config (NOT committed):**
- `~/.codex/config.toml` (Codex MCP servers + env passthrough)
- Claude Code MCP configuration (per-developer)

**Rule:** Skills may *describe* how to set up MCP servers, but should not hardcode secrets or local absolute paths.

---

## Next Iteration (Optional Skills)

If you want more automation later, add:

1. `oe-db-fixture-hygiene` — ensure runtime DB artifacts never end up tracked; generate fixtures in `tests/fixtures/`.
2. `oe-sentry-triage` — pull real prod stack traces/issues via Sentry MCP, map to code + tests.
3. `oe-yaml-flow-maintenance` — maintain YAML flow specs and keep them consistent with Python step behavior.

## Optional Curated Skills (Codex)

If you want ready-made Codex skills from the curated set, consider installing:
- `gh-fix-ci` (GitHub Actions CI break triage)
- `gh-address-comments` (address PR review comments)
- `notion-spec-to-implementation` (only if you keep specs in Notion)
