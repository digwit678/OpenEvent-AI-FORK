# V4 Step 1–4 Test Reorg Report

## Old → New Mapping

| Legacy Suite | Replacement |
| --- | --- |
| (none migrated yet) | tests/specs/intake/*, tests/specs/date/*, tests/specs/room/*, tests/specs/products_offer/*, tests/specs/gatekeeping/*, tests/specs/determinism/*, tests/specs/detours/* |

## Matrix Coverage Snapshot

| Area | Status |
| --- | --- |
| Intake loops & shortcuts | Green |
| Date confirmation (next5, blackout/buffer) | Green |
| Room availability & detours | Green |
| Products & offer send | Green |
| Gatekeeping & HIL | Green |
| Determinism & detours | Green |

## Remaining Gaps / TODOs

- TODO: Expand legacy mapping once historical suites are relocated into `tests/_legacy/`.
- TODO: Add real workflow harness coverage aligned with `docs/reports/test_matrix_v4.md` interaction logs.
