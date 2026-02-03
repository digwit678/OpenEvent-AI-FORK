# OpenEvent-AI Agent Guide (Gemini)

## Startup (keep cost low)

1. If it exists, read `docs/daily_scrum/session_primer.md` first and treat it as the current “what changed / risks / suggested checks”.
2. If the primer file is missing or stale, fall back to:
   - `DEV_CHANGELOG.md`
   - `docs/guides/TEAM_GUIDE.md` (regressions / high-risk areas)
   - `TO_DO_NEXT_SESS.md`
3. Default to read-only actions unless asked; write shareable briefs to `docs/daily_scrum/` and scratch notes to `/tmp`.

## Repo-local skills (optional, when applicable)

- Routing/state/detection changes: `.codex/skills/oe-architectural-guardrails/SKILL.md`
- Minimal tests to run: `.codex/skills/oe-test-matrix-navigator/SKILL.md`
