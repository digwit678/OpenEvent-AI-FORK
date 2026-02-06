#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path


TS_RE = re.compile(r"^(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+(?P<rest>.*)$")
SKILL_MD_RE = re.compile(r'(?P<path>(?:/[^\s"}]+|\.[^\s"}]+)SKILL\.md)')
JSON_PATH_RE = re.compile(r'"path"\s*:\s*"(?P<path>[^"]+SKILL\.md)"')
FILE_URI_RE = re.compile(r'file://(?P<path>/[^"]+SKILL\.md)')
EXEC_CMD_RE = re.compile(r'ToolCall:\s+exec_command\s+\{.*?"cmd"\s*:\s*"(?P<cmd>(?:\\.|[^"])*)"', re.DOTALL)


@dataclass(frozen=True)
class SkillEvent:
    ts: datetime
    path: str
    kind: str  # "read" | "write" | "unknown"


def _parse_utc_ts(raw: str) -> datetime | None:
    raw = raw.strip()
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _detect_kind(rest: str) -> str:
    if "*** Update File:" in rest or "write_file" in rest or "write_text_file" in rest:
        return "write"
    if "read_text_file" in rest or "read_file" in rest or "cat " in rest or "sed -n" in rest:
        return "read"
    return "unknown"


def _extract_skill_paths(rest: str) -> list[str]:
    paths: list[str] = []

    for m in JSON_PATH_RE.finditer(rest):
        paths.append(m.group("path"))

    for m in FILE_URI_RE.finditer(rest):
        paths.append(m.group("path"))

    for m in SKILL_MD_RE.finditer(rest):
        paths.append(m.group("path"))

    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p in seen:
            continue
        seen.add(p)
        out.append(p)
    return out


def _extract_exec_cmd(rest: str) -> str | None:
    m = EXEC_CMD_RE.search(rest)
    if not m:
        return None
    raw = m.group("cmd")
    try:
        return json.loads(f"\"{raw}\"")
    except json.JSONDecodeError:
        return raw


def _parse_frontmatter(skill_md_path: Path) -> tuple[dict[str, str], str | None]:
    text = skill_md_path.read_text(encoding="utf-8")
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


def _render_report(
    *,
    now: datetime,
    since: datetime,
    log_path: Path,
    events: list[SkillEvent],
    exec_cmd_counts: Counter[str],
    errors: list[str],
) -> str:
    reads = Counter(e.path for e in events if e.kind == "read")
    writes = Counter(e.path for e in events if e.kind == "write")

    read_by_skill: Counter[str] = Counter()
    write_by_skill: Counter[str] = Counter()
    paths_by_skill: dict[str, set[str]] = defaultdict(set)

    for path, count in reads.items():
        name = Path(path).parent.name
        read_by_skill[name] += count
        paths_by_skill[name].add(path)
    for path, count in writes.items():
        name = Path(path).parent.name
        write_by_skill[name] += count
        paths_by_skill[name].add(path)

    lines: list[str] = []
    lines.append("# Codex skill upskill report")
    lines.append("")
    lines.append(f"- Generated (UTC): `{now.isoformat()}`")
    lines.append(f"- Window (UTC): `{since.isoformat()}` → `{now.isoformat()}`")
    lines.append(f"- Log: `{log_path}`")
    lines.append("")

    lines.append("## Skills loaded (SKILL.md reads)")
    if not read_by_skill:
        lines.append("- None found in the time window.")
    else:
        for skill, count in read_by_skill.most_common(20):
            example_path = sorted(paths_by_skill[skill])[0]
            lines.append(f"- `{skill}`: {count} (`{example_path}`)")
    lines.append("")

    lines.append("## Skills edited (SKILL.md writes/patches)")
    if not write_by_skill:
        lines.append("- None found in the time window.")
    else:
        for skill, count in write_by_skill.most_common(20):
            example_path = sorted(paths_by_skill[skill])[0]
            lines.append(f"- `{skill}`: {count} (`{example_path}`)")
    lines.append("")

    lines.append("## Skill integrity checks (for skills seen in logs)")
    any_checks = False
    for skill in sorted(paths_by_skill.keys()):
        for path_str in sorted(paths_by_skill[skill]):
            p = Path(path_str)
            if not p.exists():
                any_checks = True
                lines.append(f"- `{skill}`: missing on disk: `{p}`")
                continue
            frontmatter, error = _parse_frontmatter(p)
            if error:
                any_checks = True
                lines.append(f"- `{skill}`: `{p}`: {error}")
                continue
            name = frontmatter.get("name", "").strip()
            description = frontmatter.get("description", "").strip()
            if name and name != p.parent.name:
                any_checks = True
                lines.append(f"- `{skill}`: `{p}`: frontmatter name `{name}` != folder `{p.parent.name}`")
            if not name or not description:
                any_checks = True
                lines.append(f"- `{skill}`: `{p}`: missing required `name` or `description`")
            size_lines = p.read_text(encoding="utf-8").count("\n") + 1
            if size_lines > 400:
                any_checks = True
                lines.append(f"- `{skill}`: `{p}`: {size_lines} lines (consider progressive disclosure into `references/`)")
    if not any_checks:
        lines.append("- No issues detected by lightweight checks.")
    lines.append("")

    lines.append("## Repeated exec_command calls (top 15)")
    if not exec_cmd_counts:
        lines.append("- None found in the time window.")
    else:
        shown = 0
        for cmd, count in exec_cmd_counts.most_common(50):
            if shown >= 15:
                break
            if "SKILL.md" in cmd:
                continue
            shown += 1
            cmd_one_line = cmd.replace("\n", "\\n")
            lines.append(f"- {count}× `{cmd_one_line}`")
    lines.append("")

    lines.append("## Suggested improvements (heuristics)")
    lines.append("- For the top 1–3 most-loaded skills, tighten the `description:` so trigger conditions are concrete (symptoms + keywords).")
    lines.append("- If the same shell snippet repeats, bundle it as a skill `scripts/` helper and update the skill to run it.")
    lines.append("- If a SKILL.md is large (>400 lines) or frequently re-opened, split details into `references/` and keep SKILL.md as a workflow + index.")
    lines.append("")

    if errors:
        lines.append("## Log errors/warnings (sample)")
        for e in errors[:30]:
            lines.append(f"- `{e.strip()}`")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit recent Codex logs for skill usage and suggest improvements.")
    parser.add_argument("--days", type=float, default=2.0, help="How many days back to scan (default: 2).")
    parser.add_argument(
        "--log",
        type=Path,
        default=Path.home() / ".codex" / "log" / "codex-tui.log",
        help="Path to Codex log file (default: ~/.codex/log/codex-tui.log).",
    )
    parser.add_argument("--out", type=Path, help="Write report to this path instead of stdout.")
    args = parser.parse_args()

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=args.days)

    if not args.log.exists():
        print(f"ERROR: log file not found: {args.log}", file=sys.stderr)
        return 2

    events: list[SkillEvent] = []
    exec_cmd_counts: Counter[str] = Counter()
    errors: list[str] = []

    with args.log.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            m = TS_RE.match(line)
            if not m:
                continue
            ts = _parse_utc_ts(m.group("ts"))
            if ts is None or ts < since:
                continue
            rest = m.group("rest")

            if " ERROR " in line or " WARN " in line:
                errors.append(line.strip())

            cmd = _extract_exec_cmd(rest)
            if cmd:
                exec_cmd_counts[cmd.strip()] += 1

            if "SKILL.md" not in rest:
                continue
            kind = _detect_kind(rest)
            for path in _extract_skill_paths(rest):
                if not path.endswith("SKILL.md"):
                    continue
                events.append(SkillEvent(ts=ts, path=path, kind=kind))

    report = _render_report(
        now=now,
        since=since,
        log_path=args.log,
        events=events,
        exec_cmd_counts=exec_cmd_counts,
        errors=errors,
    )

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report, encoding="utf-8")
        print(f"Wrote report to {args.out}")
        return 0

    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
