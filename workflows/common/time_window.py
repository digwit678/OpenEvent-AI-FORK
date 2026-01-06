"""Unified Time Window for Overlap Detection.

This module provides a centralized TimeWindow class used across all
date/time conflict detection in the system:
- Room availability conflicts
- Site visit scheduling
- Multi-day event handling

Key Principle:
    The manager configures availability; the system only checks for overlap.
    Buffer times are baked into manager-defined slots.

Overlap Algorithm:
    Two windows overlap if: window1.start < window2.end AND window2.start < window1.end
    Adjacent windows (touching end = start) do NOT overlap.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta
from typing import Any, Dict, Optional, Tuple
from zoneinfo import ZoneInfo

from workflows.io.config_store import get_timezone


def _get_venue_tz() -> ZoneInfo:
    """Get venue timezone from config."""
    return ZoneInfo(get_timezone())


@dataclass
class TimeWindow:
    """Represents a time window for overlap detection.

    All times are timezone-aware, using the venue timezone from config.

    Attributes:
        start: Start datetime (timezone-aware)
        end: End datetime (timezone-aware)
    """

    start: datetime
    end: datetime

    def overlaps(self, other: "TimeWindow") -> bool:
        """Check if this window overlaps with another.

        Uses exclusive end logic: adjacent windows (touching end = start) do NOT overlap.

        Examples:
            - 14:00-16:00 vs 16:00-18:00 → NO overlap (adjacent)
            - 14:00-16:00 vs 15:00-17:00 → OVERLAP
            - 14:00-16:00 vs 16:01-18:00 → NO overlap
        """
        return self.start < other.end and other.start < self.end

    def contains_date(self, date_iso: str) -> bool:
        """Check if a specific date falls within this window.

        Useful for multi-day events to check if a date is blocked.

        Args:
            date_iso: Date in ISO format (YYYY-MM-DD)

        Returns:
            True if the date falls within the window (any part of the day)
        """
        try:
            tz = _get_venue_tz()
            date_start = datetime.fromisoformat(date_iso).replace(
                hour=0, minute=0, second=0, microsecond=0, tzinfo=tz
            )
            date_end = date_start + timedelta(days=1)
            return self.start < date_end and date_start < self.end
        except ValueError:
            return False

    def to_iso(self) -> Tuple[str, str]:
        """Return (start_iso, end_iso) strings."""
        return self.start.isoformat(), self.end.isoformat()

    @classmethod
    def from_iso(cls, start_iso: str, end_iso: str) -> Optional["TimeWindow"]:
        """Create TimeWindow from ISO timestamp strings.

        Handles both Z (Zulu) and +00:00 timezone suffixes.

        Args:
            start_iso: Start time in ISO format (e.g., "2026-02-15T14:00:00+01:00")
            end_iso: End time in ISO format

        Returns:
            TimeWindow instance or None if parsing fails
        """
        try:
            start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            # Ensure timezone-aware
            if start_dt.tzinfo is None:
                tz = _get_venue_tz()
                start_dt = start_dt.replace(tzinfo=tz)
                end_dt = end_dt.replace(tzinfo=tz)
            return cls(start=start_dt, end=end_dt)
        except ValueError:
            return None

    @classmethod
    def from_date_and_times(
        cls,
        date_iso: str,
        start_time: Optional[str],
        end_time: Optional[str],
    ) -> Optional["TimeWindow"]:
        """Create TimeWindow from a date and time strings.

        Args:
            date_iso: Date in ISO format (YYYY-MM-DD)
            start_time: Start time as HH:MM (e.g., "14:00") or None for all-day start
            end_time: End time as HH:MM (e.g., "18:00") or None for all-day end

        Returns:
            TimeWindow instance or None if parsing fails
        """
        try:
            tz = _get_venue_tz()
            base_date = datetime.fromisoformat(date_iso).date()

            # Parse start time
            if start_time:
                parts = start_time.split(":")
                start_t = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            else:
                start_t = time(0, 0)  # Start of day

            # Parse end time
            if end_time:
                parts = end_time.split(":")
                end_t = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            else:
                end_t = time(23, 59, 59)  # End of day

            start_dt = datetime.combine(base_date, start_t, tzinfo=tz)
            end_dt = datetime.combine(base_date, end_t, tzinfo=tz)

            # Handle overnight events (end before start)
            if end_dt <= start_dt:
                end_dt += timedelta(days=1)

            return cls(start=start_dt, end=end_dt)
        except (ValueError, IndexError, TypeError):
            return None

    @classmethod
    def all_day(cls, date_iso: str) -> Optional["TimeWindow"]:
        """Create an all-day TimeWindow for a specific date.

        All-day events block any timed event on the same date.

        Args:
            date_iso: Date in ISO format (YYYY-MM-DD)

        Returns:
            TimeWindow from 00:00:00 to 23:59:59 on the given date
        """
        return cls.from_date_and_times(date_iso, None, None)

    @classmethod
    def multi_day(
        cls,
        start_date: str,
        end_date: str,
        start_time: Optional[str] = None,
        end_time: Optional[str] = None,
    ) -> Optional["TimeWindow"]:
        """Create TimeWindow spanning multiple days.

        Args:
            start_date: Start date in ISO format (YYYY-MM-DD)
            end_date: End date in ISO format (YYYY-MM-DD)
            start_time: Start time on first day as HH:MM (default: 00:00)
            end_time: End time on last day as HH:MM (default: 23:59)

        Returns:
            TimeWindow spanning from start_date start_time to end_date end_time
        """
        try:
            tz = _get_venue_tz()

            # Parse start
            start_d = datetime.fromisoformat(start_date).date()
            if start_time:
                parts = start_time.split(":")
                start_t = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            else:
                start_t = time(0, 0)
            start_dt = datetime.combine(start_d, start_t, tzinfo=tz)

            # Parse end
            end_d = datetime.fromisoformat(end_date).date()
            if end_time:
                parts = end_time.split(":")
                end_t = time(int(parts[0]), int(parts[1]) if len(parts) > 1 else 0)
            else:
                end_t = time(23, 59, 59)
            end_dt = datetime.combine(end_d, end_t, tzinfo=tz)

            # Ensure end is after start
            if end_dt <= start_dt:
                return None

            return cls(start=start_dt, end=end_dt)
        except (ValueError, IndexError, TypeError):
            return None

    @classmethod
    def from_event(cls, event_entry: Dict[str, Any]) -> Optional["TimeWindow"]:
        """Extract TimeWindow from an event entry.

        Tries multiple sources in order of preference:
        1. requested_window.start/end (full ISO timestamps)
        2. chosen_date + event_data Start/End Time
        3. chosen_date only (all-day)

        Also handles multi-day events if end_date/end_date_iso is present.

        Args:
            event_entry: Event dictionary from database

        Returns:
            TimeWindow or None if insufficient date/time info
        """
        # Priority 1: Full ISO timestamps from requested_window
        requested_window = event_entry.get("requested_window") or {}
        if requested_window.get("start") and requested_window.get("end"):
            return cls.from_iso(requested_window["start"], requested_window["end"])

        # Priority 2: Build from chosen_date + times
        chosen_date = event_entry.get("chosen_date")
        if not chosen_date:
            return None

        # Convert DD.MM.YYYY to ISO if needed
        if "." in chosen_date:
            try:
                day, month, year = map(int, chosen_date.split("."))
                start_date_iso = f"{year:04d}-{month:02d}-{day:02d}"
            except (ValueError, IndexError):
                return None
        else:
            start_date_iso = chosen_date

        # Check for multi-day event
        end_date = event_entry.get("end_date_iso") or event_entry.get("end_date")
        if end_date:
            # Convert DD.MM.YYYY to ISO if needed
            if "." in end_date:
                try:
                    day, month, year = map(int, end_date.split("."))
                    end_date_iso = f"{year:04d}-{month:02d}-{day:02d}"
                except (ValueError, IndexError):
                    end_date_iso = start_date_iso
            else:
                end_date_iso = end_date

            # Get times from event_data or requirements
            event_data = event_entry.get("event_data") or {}
            requirements = event_entry.get("requirements") or {}
            duration = requirements.get("event_duration") or {}

            start_time = (
                duration.get("start")
                or event_data.get("Start Time")
            )
            end_time = (
                duration.get("end")
                or event_data.get("End Time")
            )

            # Filter "Not specified"
            if start_time == "Not specified":
                start_time = None
            if end_time == "Not specified":
                end_time = None

            return cls.multi_day(start_date_iso, end_date_iso, start_time, end_time)

        # Single-day event
        event_data = event_entry.get("event_data") or {}
        requirements = event_entry.get("requirements") or {}
        duration = requirements.get("event_duration") or {}

        start_time = (
            duration.get("start")
            or event_data.get("Start Time")
        )
        end_time = (
            duration.get("end")
            or event_data.get("End Time")
        )

        # Filter "Not specified"
        if start_time == "Not specified":
            start_time = None
        if end_time == "Not specified":
            end_time = None

        return cls.from_date_and_times(start_date_iso, start_time, end_time)


def windows_overlap(window1: Optional[TimeWindow], window2: Optional[TimeWindow]) -> bool:
    """Check if two windows overlap, with None handling.

    If either window is None, falls back to assuming overlap (safe default).

    Args:
        window1: First TimeWindow or None
        window2: Second TimeWindow or None

    Returns:
        True if windows overlap OR if either is None (conservative default)
    """
    if window1 is None or window2 is None:
        return True  # Conservative: assume overlap if we can't determine
    return window1.overlaps(window2)


__all__ = [
    "TimeWindow",
    "windows_overlap",
]
