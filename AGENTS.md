# OpenEvent-AI Agent Instructions (Codex)

## Session primer (cheap + always current)

1. If it exists, read `docs/daily_scrum/session_primer.md` first and treat it as the source of truth for:
   - what changed recently
   - current risk areas (routing/detection/workflow/site-visit/billing/HIL/fallback)
   - suggested quick checks + smallest relevant test subset
2. If it exists, also skim `docs/daily_scrum/weekly_agent_pack.md` for the broader weekly context (startup packs + docs triage).
3. If the primer file is missing or stale, fall back to:
   - `DEV_CHANGELOG.md`
   - `docs/guides/TEAM_GUIDE.md` (focus on regressions / high-risk areas)
   - `TO_DO_NEXT_SESS.md`

**Primer path:** `docs/daily_scrum/session_primer.md`
**Weekly pack path:** `docs/daily_scrum/weekly_agent_pack.md`

## No-conflict rules (safe alongside PyCharm/IDEA)

- Default to **read-only** actions (git/rg/view) unless the user explicitly asks for code changes.
- Avoid auto-running long/expensive commands (formatters, installs, servers, full test suites).
- Write shareable briefs to `docs/daily_scrum/` and scratch notes to `/tmp` to avoid git noise/conflicts.
- Save ad-hoc artifacts under `artifacts/` (examples: `artifacts/screenshots/`, `artifacts/requests/`).
- Playwright screenshots should stay in `.playwright-mcp/` (auto output).

## Skills (repo-local)

- Routing/state/detection changes: `.codex/skills/oe-architectural-guardrails/SKILL.md`
- Minimal tests to run: `.codex/skills/oe-test-matrix-navigator/SKILL.md`
- Workflow bug triage: `.codex/skills/oe-workflow-triage/SKILL.md`
- Site-visit flow verification: `.codex/skills/oe-e2e-site-visit/SKILL.md`
