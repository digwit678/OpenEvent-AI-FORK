# Claude Code Instructions

- Canonical project memory lives in `.claude/skills/`; consult relevant Skills before changing the email workflow.
- Keep this file short and policy-only; move detailed guidance into Skills with links.
- After non-trivial work, add durable learnings to a Skill (manual edit or `scripts/skills/retrospective.py`) and validate with `python scripts/skills/validate_skills.py`.
- For OpenEvent email workflow changes, start with `.claude/skills/openevent-email-workflow/SKILL.md` and `.claude/skills/openevent-email-change-checklist/SKILL.md`.

## Coding Guidelines

### Variable Naming

Use **explanatory variable names** that reflect the business logic, not the data model structure:

```python
# Bad - reflects data model structure
features = config.get("features")
equipment = config.get("equipment")

# Good - reflects what the data represents in context
available_in_room = _get_all_room_items(config)
requested_item = product.lower().strip()
has_flipchart = any("flip" in token for token in available_in_room)
```

This makes code self-documenting and easier to maintain. The reader shouldn't need to know the underlying JSON schema to understand what the code does.
