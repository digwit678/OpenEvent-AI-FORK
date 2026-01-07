"""Safe error handling utilities for API routes.

Prevents leaking internal exception details to clients while preserving
full debugging information in server logs.
"""

from __future__ import annotations

import logging
from typing import NoReturn

from fastapi import HTTPException


def raise_safe_error(
    status_code: int,
    context: str,
    exc: Exception,
    logger: logging.Logger,
) -> NoReturn:
    """Log full exception details and raise HTTPException with sanitized message.

    Args:
        status_code: HTTP status code to return (e.g., 500, 404)
        context: Human-readable context for the error (e.g., "load config", "approve task")
        exc: The original exception that was caught
        logger: Logger instance for recording the full exception

    Raises:
        HTTPException: With sanitized detail message

    Example:
        try:
            result = load_config()
        except Exception as exc:
            raise_safe_error(500, "load config", exc, logger)
    """
    logger.exception("Error during %s: %s", context, exc)
    raise HTTPException(
        status_code=status_code,
        detail=f"Failed to {context}. Please try again or contact support.",
    ) from exc


def safe_error_detail(context: str) -> str:
    """Generate a sanitized error detail message.

    For cases where you need the message string without raising.
    """
    return f"Failed to {context}. Please try again or contact support."
