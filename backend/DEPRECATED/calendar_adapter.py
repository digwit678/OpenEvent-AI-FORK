"""Shim module re-exporting calendar helpers from backend.adapters."""

# DEPRECATED: Legacy wrapper kept for compatibility. Do not add workflow logic here.
# Intake/Date/Availability live in backend/workflows/groups/* and are orchestrated by workflow_email.py.

from backend.adapters.calendar_adapter import CalendarAdapter, ensure_calendar_dir

__all__ = ["CalendarAdapter", "ensure_calendar_dir"]
