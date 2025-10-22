#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


def _load_records(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text()
    records: List[Dict[str, Any]] = []
    buf: List[str] = []
    depth = 0
    for ch in text:
        if ch == '{':
            if depth == 0:
                buf = []
            depth += 1
            buf.append(ch)
        elif ch == '}':
            buf.append(ch)
            depth -= 1
            if depth == 0:
                records.append(json.loads(''.join(buf)))
        else:
            if depth > 0:
                buf.append(ch)
    return records


def _hil_gate(records: List[Dict[str, Any]]) -> bool:
    seen_room_result = False
    for rec in records:
        if (rec.get('action') or '').lower() == 'room_avail_result':
            seen_room_result = True
        if (rec.get('action') or '').lower() == 'offer_draft_prepared':
            msg_id = (rec.get('msg_id') or '').lower()
            if 'hil' in msg_id and seen_room_result:
                return True
    return False


def _confirmation_hil(records: List[Dict[str, Any]]) -> bool:
    for idx, rec in enumerate(records):
        if (rec.get('action') or '').lower() == 'confirmation_finalized':
            if 'hil' not in (rec.get('msg_id') or '').lower():
                continue
            prior = records[:idx]
            if any((p.get('action') or '').lower() in {
                'transition_ready',
                'confirmation_draft',
                'confirmation_deposit_requested',
                'confirmation_reserve',
                'confirmation_site_visit',
                'confirmation_deposit_notified',
            } for p in prior):
                return True
    return False


def _detours(records: List[Dict[str, Any]]) -> bool:
    caller_set = False
    caller_cleared = False
    return_audit = False
    detour_step_seen = False
    for rec in records:
        state = rec.get('state') or {}
        caller = state.get('caller')
        if caller is not None:
            caller_set = True
        elif caller_set and caller is None:
            caller_cleared = True
        step = state.get('step')
        audit = rec.get('audit_tail') or {}
        if step in {2, 3, 4} and audit.get('from_step') is not None:
            detour_step_seen = True
        if audit.get('reason') == 'return_to_caller':
            return_audit = True
    return caller_set and caller_cleared and return_audit and detour_step_seen


def _thread_fsm(records: List[Dict[str, Any]]) -> bool:
    allowed = {'Awaiting Client Response', 'In Progress', None}
    threads = [ (rec.get('state') or {}).get('thread') for rec in records ]
    if any(thread not in allowed for thread in threads):
        return False
    has_awaiting = any(thread == 'Awaiting Client Response' for thread in threads)
    has_in_progress = any(thread == 'In Progress' for thread in threads)
    return has_awaiting and has_in_progress


def _audit(records: List[Dict[str, Any]]) -> bool:
    prev_step = None
    for rec in records:
        state = rec.get('state') or {}
        step = state.get('step')
        if step is not None and prev_step is not None and step != prev_step:
            audit = rec.get('audit_tail') or {}
            if audit.get('from_step') is None:
                return False
        prev_step = step if step is not None else prev_step
    if not any((rec.get('audit_tail') or {}).get('reason') == 'return_to_caller' for rec in records):
        return False
    return True


def _confirmation_variant(records: List[Dict[str, Any]]) -> bool:
    for rec in records:
        action = (rec.get('action') or '').lower()
        draft = (rec.get('draft_topic') or '').lower()
        if any(token in action for token in ('confirm', 'reserve', 'site_visit', 'deposit')):
            return True
        if any(token in draft for token in ('confirm', 'reserve', 'site_visit', 'deposit')):
            return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate manual UX run against expectations.")
    parser.add_argument('path', type=Path, help='Path to the JSON trace produced by a manual UX scenario run')
    args = parser.parse_args()

    records = _load_records(args.path)
    if not records:
        raise SystemExit('No records parsed from trace.')

    results = {
        'hil_gate': _hil_gate(records),
        'confirmation_hil': _confirmation_hil(records),
        'detours': _detours(records),
        'thread_fsm': _thread_fsm(records),
        'audit': _audit(records),
        'confirmation_variant': _confirmation_variant(records),
    }
    print(json.dumps(results, indent=2))


if __name__ == '__main__':
    main()
