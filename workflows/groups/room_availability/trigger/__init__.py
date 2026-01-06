"""DEPRECATED: Use backend.workflows.steps.step3_room_availability.trigger instead."""
from workflows.steps.step3_room_availability.trigger.process import (
    evaluate_room_statuses,
    process,
)

__all__ = ["evaluate_room_statuses", "process"]
