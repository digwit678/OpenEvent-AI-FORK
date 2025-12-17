# Pending Refactoring Tasks

## Phase C - Large File Splitting (In Progress)

### main.py Route Extraction

**Status:** 🔄 In Progress (47% complete - 1018 lines removed)

| Route Group | Status | Target File | Lines |
|-------------|--------|-------------|-------|
| Tasks (`/api/tasks/*`) | ✅ Done | `routes/tasks.py` | ~230 |
| Events (`/api/events/*`) | ✅ Done | `routes/events.py` | ~180 |
| Config (`/api/config/*`) | ✅ Done | `routes/config.py` | ~175 |
| Clients (`/api/client/*`) | ✅ Done | `routes/clients.py` | ~135 |
| Debug (`/api/debug/*`) | ✅ Done | `routes/debug.py` | ~190 |
| Snapshots (`/api/snapshots/*`) | ✅ Done | `routes/snapshots.py` | ~60 |
| Test Data (`/api/test-data/*`, `/api/qna`) | ✅ Done | `routes/test_data.py` | ~160 |
| Workflow (`/api/workflow/*`) | ✅ Done | `routes/workflow.py` | ~35 |
| Messages (`/api/send-message`, etc.) | ⏳ Pending | `routes/messages.py` | ~280 |
| Conversation (`/api/conversation/*`) | ⏳ Pending | (in messages.py) | ~100 |

**Current state:** main.py reduced from 2188 → 1170 lines (47% reduction)

### Other Large Files (Deferred)

These files were analyzed but deferred due to high risk of breaking functionality:

| File | Lines | Status | Notes |
|------|-------|--------|-------|
| `step2_handler.py` | 3665 | ⏳ Deferred | Date confirmation - heavy interdependencies |
| `smart_shortcuts.py` | 2196 | ⏳ Deferred | Shortcut detection - shared state |
| `general_qna.py` | ~1350 | ✅ Partial | Constants/utils extracted to `qna/` |

**Rationale:** Heavy interdependencies, shared state, conditional logic - splitting risks breaking functionality. See `docs/internal/OPEN_DECISIONS.md` DECISION-006.

## Recommended Next Steps

### For main.py (remaining ~380 lines of routes to extract):

1. **Messages routes** → `backend/api/routes/messages.py`
   - `/api/start-conversation` (~130 lines)
   - `/api/send-message` (~150 lines)
   - Contains core conversation logic, most complex
   - Helper functions: `_extract_workflow_reply`, `_update_event_info_from_db`, etc.

2. **Conversation routes** (can be in messages.py or separate)
   - `/api/conversation/{session_id}/confirm-date`
   - `/api/accept-booking/{session_id}`
   - `/api/reject-booking/{session_id}`
   - `/api/conversation/{session_id}` (GET)

### What to keep in main.py (~600 lines):

These belong in main.py as app lifecycle/infrastructure:
- FastAPI app creation and setup (~50 lines)
- CORS middleware configuration (~20 lines)
- Port management functions (~90 lines)
- Frontend launch functions (~80 lines)
- Lifespan management (~20 lines)
- Root endpoint (~10 lines)
- Process cleanup functions (~80 lines)
- Startup code (`if __name__ == "__main__"`) (~20 lines)

## Completed Phases

| Phase | Status | Commits |
|-------|--------|---------|
| A (prep) | ✅ Complete | - |
| B (detection) | ✅ Complete | - |
| C (large files) | 🔄 Partial | `57651b8`, `73cb07f`, `20f7901` |
| D (error handling) | ✅ Complete | - |
| E (folder renaming) | ✅ Complete | `65e7ddc` |
| F (file renaming) | ✅ Complete | `366e465` |

## Known Issues from Refactoring

### Missing re-exports (Fixed in `361888e`)
- Re-export shims need ALL symbols that are imported from the original files
- Watch for dynamic imports via `getattr()` and `# type: ignore` imports
- Fixed: step2, step3, step4 process.py shims

### Import path updates needed
- Files inside `steps/` should import from canonical `steps/` paths, not deprecated `groups/` paths
- Fixed: step4_handler.py → imports from step5_negotiation (not negotiation_close)

---
Last updated: 2025-12-18
