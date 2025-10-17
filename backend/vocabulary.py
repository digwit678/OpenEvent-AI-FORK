"""Shim module re-exporting enumerations from backend.domain."""

# DEPRECATED: Legacy wrapper kept for compatibility. Do not add workflow logic here.
# Intake/Date/Availability live in backend/workflows/groups/* and are orchestrated by workflow_email.py.

from backend.domain.vocabulary import IntentLabel, TaskStatus, TaskType

__all__ = ["IntentLabel", "TaskStatus", "TaskType"]
