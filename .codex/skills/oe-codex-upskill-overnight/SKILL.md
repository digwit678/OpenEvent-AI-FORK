---
name: oe-codex-upskill-overnight
description: Audits the last 1–2 days of Codex sessions/logs to see how skills/scripts were used, then suggests improvements (and can apply small fixes to SKILL.md + bundled scripts when requested).
---

# oe-codex-upskill-overnight

## Goal

Upskill Codex by continuously improving skills and bundled scripts based on *recent real usage* (last ~24–48h).

## Quick start (read-only)

1. Generate a report from recent Codex logs:
   - `python .codex/skills/oe-codex-upskill-overnight/scripts/audit_codex_skill_usage.py --days 2`
2. Pick the **top 1–3** high-signal changes (keep it PR-sized).
3. Validate skills structure:
   - `python scripts/skills/validate_skills.py --skills-dir .codex/skills`

## What to improve (high leverage)

- **Frontmatter description**: Make trigger conditions concrete (symptoms + domain keywords) so the right skill fires without guesswork.
- **Bundle scripts for repeated command sequences**: If a shell snippet gets repeated across sessions, turn it into `scripts/<thing>.py|.sh` inside the skill and update the skill to “run the script”.
- **Progressive disclosure**: If a SKILL.md is large/noisy, move details into `references/` and keep SKILL.md as a navigation + workflow.
- **Guardrails**: Add “do not run long commands / do not modify working tree unless asked” where it prevents recurring footguns.

## Apply changes (only when requested)

If asked to implement fixes:

1. Keep the patch small and focused (one skill at a time).
2. Prefer adding/adjusting scripts over expanding SKILL.md prose.
3. Re-run:
   - `python scripts/skills/validate_skills.py --skills-dir .codex/skills`
4. If you changed a Python script, at minimum:
   - `python -m py_compile .codex/skills/oe-codex-upskill-overnight/scripts/audit_codex_skill_usage.py`

## Guardrails

- Default to **report + suggestions** (read-only).
- Do not run installs, formatters, servers, or full test suites unless explicitly requested.

