"""Shim module re-exporting GUI adapters from backend.adapters."""

# DEPRECATED: Legacy wrapper kept for compatibility. Do not add workflow logic here.
# Intake/Date/Availability live in backend/workflows/groups/* and are orchestrated by workflow_email.py.

from backend.adapters.client_gui_adapter import ClientGUIAdapter

__all__ = ["ClientGUIAdapter"]
