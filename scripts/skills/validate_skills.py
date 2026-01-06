#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")
MAX_LINES_WARN = 400
MAX_BYTES_WARN = 20_000


def parse_frontmatter(text: str) -> tuple[dict[str, str], str | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "missing frontmatter start (---)"
    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return {}, "missing frontmatter end (---)"
    data: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
    return data, None


def validate_skill(skill_dir: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        errors.append(f"{skill_dir}: missing SKILL.md")
        return errors, warnings

    text = skill_md.read_text(encoding="utf-8")
    frontmatter, error = parse_frontmatter(text)
    if error:
        errors.append(f"{skill_md}: {error}")
        return errors, warnings

    name = frontmatter.get("name", "").strip()
    description = frontmatter.get("description", "").strip()

    if not name:
        errors.append(f"{skill_md}: frontmatter missing name")
    if not description:
        errors.append(f"{skill_md}: frontmatter missing description")

    if name and name != skill_dir.name:
        errors.append(f"{skill_md}: frontmatter name '{name}' does not match folder '{skill_dir.name}'")

    if name and not NAME_PATTERN.match(name):
        errors.append(f"{skill_md}: name '{name}' must match {NAME_PATTERN.pattern}")

    line_count = text.count("\n") + 1
    if line_count > MAX_LINES_WARN:
        warnings.append(f"{skill_md}: {line_count} lines (consider progressive disclosure)")
    if len(text.encode("utf-8")) > MAX_BYTES_WARN:
        warnings.append(f"{skill_md}: {len(text.encode('utf-8'))} bytes (consider progressive disclosure)")

    return errors, warnings


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate .claude/skills SKILL.md files")
    parser.add_argument("--skills-dir", default=".claude/skills", help="Path to skills root")
    args = parser.parse_args()

    skills_dir = Path(args.skills_dir)
    if not skills_dir.exists():
        print(f"Skills directory not found: {skills_dir}", file=sys.stderr)
        return 1

    errors: list[str] = []
    warnings: list[str] = []

    for skill_dir in sorted(p for p in skills_dir.iterdir() if p.is_dir()):
        skill_errors, skill_warnings = validate_skill(skill_dir)
        errors.extend(skill_errors)
        warnings.extend(skill_warnings)

    for warning in warnings:
        print(f"WARN: {warning}", file=sys.stderr)

    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(f"Validated {len([p for p in skills_dir.iterdir() if p.is_dir()])} skills.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
