"""
Runtime workflow modules.

This package contains extracted runtime components from the main workflow_email.py:
- hil_tasks: HIL task management (approve, reject, cleanup) [W2]
- router: Step routing loop and dispatch [W3]
- pre_route: Pre-routing pipeline (duplicate detection, guards, shortcuts) [P1]
"""
