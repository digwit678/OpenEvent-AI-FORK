---
name: oe-workflow-debug-quickstart
description: Rapidly set up a debug environment for workflow issues. Useful for reproducing bugs, verifying fixes, and inspecting logs without full E2E overhead.
---

# oe-workflow-debug-quickstart

## Purpose
Quickly bootstrap a debugging session for OpenEvent workflow logic.

## Steps

1. **Ensure Clean State**
   - Stop existing servers: `./scripts/dev/dev_server.sh stop`
   - Clear temp logs: `rm -rf tmp-debug/*`

2. **Start Backend in Debug Mode**
   - Run: `./scripts/dev/dev_server.sh start`
   - Check status: `./scripts/dev/dev_server.sh status`

3. **Run Reproduction Script**
   - Select a scenario from `scripts/manual_ux/` (e.g., `manual_ux_scenario_I.py`).
   - Run: `python3 scripts/manual_ux/manual_ux_scenario_I.py`

4. **Inspect Live Logs**
   - Tail the latest log: `tail -f tmp-debug/live/*.log`

## Related Skills
- `oe-workflow-triage`: For deep-dive analysis and fix planning.
- `oe-backend-startup-triage`: If the server fails to start.
