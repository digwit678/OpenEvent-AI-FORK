# Test Suite Inventory

_Last updated: 2025-12-28 (py311, AGENT_MODE=stub)._

This file replaces the stale November inventory. Instead of per-file pass/fail tables, we track suites at the directory level, include the current test counts, and document how to re-run them. Detailed regression guard expectations continue to live in `tests/TEST_MATRIX_detection_and_flow.md` and `docs/guides/TEAM_GUIDE.md`.

---

## Snapshot

| Suite | Path | Test Count* | Health | Notes |
| --- | --- | --- | --- | --- |
| Specs (workflow expectations, UX, gatekeeping tables) | `tests/specs/` | 175 | 🟡 Partial | Verified: `tests/specs/room` + `tests/specs/ux/test_hybrid_queries_and_room_dates.py`, `tests/specs/ux/test_message_hygiene_and_continuations.py`, `tests/specs/ux/test_timeline_export.py`. |
| Workflow step harness | `tests/workflows/` | 153 | ⚪ Not run | Run with `pytest tests/workflows -n auto`. |
| Backend detection / regression / flow guards | `backend/tests/` | 538 | ⚪ Not run | Includes smoke, regression, detection DAG, and workflow guards. Run `pytest backend/tests -m "not integration"`. |
| Gatekeeping | `tests/gatekeeping/` | 3 | ✅ Pass (2025-12-28) | Guard rails for room/step progression. |
| Room ranking | `tests/room/` | 1 | ⚪ Not run | Deterministic ranking helper. |
| Flow specs (YAML) | `tests/flows/` | 10 | ⚪ Not run | Uses YAML transcripts; still being modernised. Run `pytest tests/flows/test_flow_specs.py -k flow_`. |
| Stubbed e2e v4 | `tests/e2e_v4/` | 1 | ⚪ Not run | Smoke path that doesn’t call OpenAI. |
| Regression adapters | `tests/regression/` | 1 | ⚪ Not run | Matrix parameter loader. |
| Dev UX placeholder | `tests/ux/` | 0 | Placeholder | File exists but contains no active tests yet. |
| Legacy v3 suites | `tests/_legacy/` | 20 | ❌ XFail (intentional) | Kept for historical reference. Run with `pytest -m legacy`. |
| Frontend smoke / CLI stubs | `tests/e2e/` | 0 | Placeholder | Use Playwright E2E instead. |
| Integration (live OpenAI) | `backend/tests_integration/` | 4 | ⚪ Requires AGENT_MODE=openai | Run only when real keys are configured. |
| Backend smoke | `backend/tests/smoke/` | 1 | ⚪ Not run | Verifies `load_openai_api_key`. |

_\*Test counts are produced via `rg -o "def test_" <path> | wc -l` and give a quick approximation. Parametrised tests inflate runtime counts._

---

## How to Regenerate This Table

From repo root:

```bash
# Count tests in a directory
rg -o "def test_" tests/specs | wc -l

# Capture pytest status for a suite
PYTHONDONTWRITEBYTECODE=1 pytest tests/specs -n auto --maxfail=1
```

Document the date, Python version, and any failing markers whenever the suite status changes. For cross-team visibility, add a short entry to `DEV_CHANGELOG.md` when suites flip between ✅/🟡/❌.

---

## Legacy & Placeholder Suites

- `tests/_legacy/` keeps v3 reference tests and intentionally xfails; do **not** delete without migrating the coverage.
- `tests/ux/` and `tests/e2e/` are scaffolding for future suites. When adding real tests, remember to update the counts above.
- Playwright E2E coverage lives outside `pytest`; see `oe-e2e-site-visit` skill and `atelier-ai-frontend/tests/e2e` for the latest flows.

---

## Quick Reference Commands

```bash
# Full deterministic backend + workflow sweep (fastest first)
PYTHONDONTWRITEBYTECODE=1 pytest backend/tests -m "not integration" -n auto
PYTHONDONTWRITEBYTECODE=1 pytest tests/specs tests/workflows -n auto

# Flow/YAML harness
PYTHONDONTWRITEBYTECODE=1 pytest tests/flows/test_flow_specs.py -k flow_

# Integration (OpenAI live) – run only when AGENT_MODE=openai
AGENT_MODE=openai OPENAI_TEST_MODE=1 PYTHONDONTWRITEBYTECODE=1 pytest backend/tests_integration -m integration -n 0
```

Keep this document fresh whenever suites are added, removed, or change health. If a directory gains multiple failing tests, open a ticket and annotate the table instead of letting the status drift.
