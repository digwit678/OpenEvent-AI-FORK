#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import sys
from datetime import date
from pathlib import Path
import re

NAME_PATTERN = re.compile(r"^[a-z0-9-]+$")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str | None, int | None]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, "missing frontmatter start (---)", None
    end_index = None
    for idx in range(1, len(lines)):
        if lines[idx].strip() == "---":
            end_index = idx
            break
    if end_index is None:
        return {}, "missing frontmatter end (---)", None
    data: dict[str, str] = {}
    for line in lines[1:end_index]:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        data[key.strip()] = value.strip().strip("\"'")
    return data, None, end_index


def read_note(path: str | None) -> str:
    if path:
        note = Path(path).read_text(encoding="utf-8")
    else:
        if sys.stdin.isatty():
            raise ValueError("No input provided. Use --input or pipe stdin.")
        note = sys.stdin.read()
    note = note.strip()
    if not note:
        raise ValueError("Note input is empty.")
    return note


def ensure_valid_name(name: str) -> None:
    if not NAME_PATTERN.match(name):
        raise ValueError(f"Skill name '{name}' must match {NAME_PATTERN.pattern}")


def build_note_block(note: str) -> list[str]:
    today = date.today().isoformat()
    lines = [f"### {today}"]
    lines.extend(note.splitlines())
    return lines


def append_to_section(lines: list[str], section: str, note_block: list[str]) -> list[str]:
    header = f"## {section}"
    section_start = None
    for idx, line in enumerate(lines):
        if line.strip() == header:
            section_start = idx
            break
    if section_start is None:
        lines = lines + ["", header]
        section_start = len(lines) - 1

    section_end = len(lines)
    for idx in range(section_start + 1, len(lines)):
        if lines[idx].startswith("## "):
            section_end = idx
            break

    insert_lines = []
    if section_end > 0 and lines[section_end - 1].strip():
        insert_lines.append("")
    insert_lines.extend(note_block)
    insert_lines.append("")
    return lines[:section_end] + insert_lines + lines[section_end:]


def write_or_diff(path: Path, original: str, updated: str, write: bool) -> None:
    if original == updated:
        print(f"No changes for {path}")
        return

    if write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(updated, encoding="utf-8")
        print(f"Updated {path}")
        return

    diff = difflib.unified_diff(
        original.splitlines(),
        updated.splitlines(),
        fromfile=str(path),
        tofile=str(path),
        lineterm="",
    )
    print("\n".join(diff))


def main() -> int:
    parser = argparse.ArgumentParser(description="Append retrospective notes to Claude skills")
    parser.add_argument("--input", "-i", help="Markdown note file path (or use stdin)")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--skill", help="Existing skill name to update")
    group.add_argument("--new-skill", help="New skill name to create")
    parser.add_argument("--description", help="Description for new skills")
    parser.add_argument("--section", default="Retrospective Notes", help="Section heading to append")
    parser.add_argument("--skills-dir", default=".claude/skills", help="Skills root directory")
    parser.add_argument("--write", action="store_true", help="Write changes (default is dry run)")
    args = parser.parse_args()

    note = read_note(args.input)
    skills_dir = Path(args.skills_dir)
    note_block = build_note_block(note)

    if args.skill:
        skill_name = args.skill.strip()
        ensure_valid_name(skill_name)
        skill_path = skills_dir / skill_name / "SKILL.md"
        if not skill_path.exists():
            raise FileNotFoundError(f"Skill not found: {skill_path}")
        original = skill_path.read_text(encoding="utf-8")
        frontmatter, error, _ = parse_frontmatter(original)
        if error:
            raise ValueError(f"{skill_path}: {error}")
        if frontmatter.get("name") != skill_name:
            raise ValueError(f"{skill_path}: frontmatter name does not match folder")
        if not frontmatter.get("description"):
            raise ValueError(f"{skill_path}: frontmatter missing description")

        updated_lines = append_to_section(original.splitlines(), args.section, note_block)
        updated = "\n".join(updated_lines).rstrip() + "\n"
        write_or_diff(skill_path, original, updated, args.write)
        return 0

    skill_name = args.new_skill.strip()
    ensure_valid_name(skill_name)
    if not args.description:
        raise ValueError("--description is required when creating a new skill")
    skill_dir = skills_dir / skill_name
    skill_path = skill_dir / "SKILL.md"
    if skill_path.exists():
        raise FileExistsError(f"Skill already exists: {skill_path}")

    header = [
        "---",
        f"name: {skill_name}",
        f"description: {args.description.strip()}",
        "---",
        "",
        "## When to use",
        f"- Use when working on {skill_name} tasks described below.",
        "",
        f"## {args.section}",
    ]
    content_lines = header + note_block + [""]
    updated = "\n".join(content_lines)
    write_or_diff(skill_path, "", updated, args.write)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, FileNotFoundError, FileExistsError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
