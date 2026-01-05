"""
Error Alerting Service

Sends email alerts when workflow errors occur in production.
Instead of sending confusing fallback messages to clients, errors are:
1. Suppressed from client communication
2. Reported to configured admin email addresses

This allows the team to immediately investigate and respond manually.
"""

from __future__ import annotations

import os
import smtplib
import traceback
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo
import logging

from backend.workflows.io.config_store import (
    get_timezone,
    get_from_email,
    get_from_name,
    get_venue_name,
)

logger = logging.getLogger(__name__)

# Environment check - errors only suppressed in production
_IS_DEV = os.getenv("ENV", "dev").lower() in ("dev", "development", "local")

# Startup validation flag - set by validate_alerting_config_on_startup
_ALERTING_VALIDATED = False
_ALERTING_DISABLED_SUPPRESSION = False


# =============================================================================
# Configuration
# =============================================================================

def get_error_alerting_config() -> Dict[str, Any]:
    """
    Get error alerting configuration.

    Returns config with:
        enabled: bool - Whether alerting is active
        alert_emails: list[str] - Emails to receive alerts
        smtp settings for sending
    """
    from backend.workflow_email import load_db
    from backend.services.hil_email_notification import get_hil_email_config

    # Get SMTP settings from HIL email config (shared infrastructure)
    hil_config = get_hil_email_config()

    config = {
        "enabled": True,  # Default: enabled
        "alert_emails": ["river@more-life.ch"],  # Default: OpenEvent support
        "smtp_host": hil_config.get("smtp_host", "smtp.gmail.com"),
        "smtp_port": hil_config.get("smtp_port", 587),
        "smtp_user": hil_config.get("smtp_user"),
        "smtp_password": hil_config.get("smtp_password"),
        "from_email": hil_config.get("from_email"),
        "from_name": hil_config.get("from_name"),
    }

    # Check database config
    try:
        db = load_db()
        alerting_config = db.get("config", {}).get("error_alerting", {})
        if alerting_config:
            config["enabled"] = alerting_config.get("enabled", True)
            config["alert_emails"] = alerting_config.get(
                "alert_emails", ["river@more-life.ch"]
            )
    except Exception as e:
        logger.warning(f"[ERROR_ALERT] Failed to load DB config: {e}")

    return config


def is_error_alerting_enabled() -> bool:
    """Check if error alerting is enabled and configured."""
    config = get_error_alerting_config()
    return (
        config["enabled"]
        and config["alert_emails"]
        and config["smtp_user"]
        and config["smtp_password"]
    )


def should_suppress_client_errors() -> bool:
    """
    Check if errors should be suppressed from client messages.

    In production (ENV=prod): Always suppress errors, send alerts instead
    In development (ENV=dev): Show errors in responses for debugging
    """
    return not _IS_DEV


# =============================================================================
# Email Templates
# =============================================================================

def _build_error_alert_html(
    error_type: str,
    error_message: str,
    client_email: str,
    client_name: str,
    original_message: str,
    workflow_step: Optional[str] = None,
    event_id: Optional[str] = None,
    stack_trace: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Build HTML email for error alert."""
    venue_name = get_venue_name()
    tz = ZoneInfo(get_timezone())
    timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")

    context_html = ""
    if additional_context:
        context_items = "".join(
            f"<li><strong>{k}:</strong> {v}</li>"
            for k, v in additional_context.items()
        )
        context_html = f"""
        <div style="background: #e9ecef; padding: 15px; border-radius: 8px; margin: 15px 0;">
            <h4 style="margin: 0 0 10px 0;">Additional Context</h4>
            <ul style="margin: 0; padding-left: 20px;">{context_items}</ul>
        </div>
        """

    stack_html = ""
    if stack_trace:
        stack_html = f"""
        <details style="margin: 15px 0;">
            <summary style="cursor: pointer; color: #6c757d;">Stack Trace (click to expand)</summary>
            <pre style="background: #f8f9fa; padding: 15px; border-radius: 8px; overflow-x: auto; font-size: 12px; margin-top: 10px;">{stack_trace}</pre>
        </details>
        """

    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; line-height: 1.6; color: #333; max-width: 700px; margin: 0 auto; padding: 20px;">
        <div style="background: linear-gradient(135deg, #dc3545 0%, #c82333 100%); color: white; padding: 20px; border-radius: 8px 8px 0 0;">
            <h2 style="margin: 0;">Workflow Error Alert</h2>
            <p style="margin: 5px 0 0 0; opacity: 0.9;">{venue_name} - {timestamp}</p>
        </div>

        <div style="background: white; border: 1px solid #e9ecef; border-top: none; padding: 20px; border-radius: 0 0 8px 8px;">

            <div style="background: #f8d7da; border-left: 4px solid #dc3545; padding: 15px; margin-bottom: 20px;">
                <h4 style="margin: 0 0 5px 0; color: #721c24;">{error_type}</h4>
                <p style="margin: 0; color: #721c24;">{error_message}</p>
            </div>

            <h4 style="margin: 20px 0 10px 0;">Client Information</h4>
            <table style="width: 100%; border-collapse: collapse;">
                <tr><td style="padding: 5px 0;"><strong>Name:</strong></td><td>{client_name}</td></tr>
                <tr><td style="padding: 5px 0;"><strong>Email:</strong></td><td><a href="mailto:{client_email}">{client_email}</a></td></tr>
                <tr><td style="padding: 5px 0;"><strong>Event ID:</strong></td><td>{event_id or 'N/A'}</td></tr>
                <tr><td style="padding: 5px 0;"><strong>Step:</strong></td><td>{workflow_step or 'Unknown'}</td></tr>
            </table>

            <h4 style="margin: 20px 0 10px 0;">Original Client Message</h4>
            <div style="background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px;">
                <pre style="margin: 0; white-space: pre-wrap; font-family: inherit;">{original_message}</pre>
            </div>

            {context_html}
            {stack_html}

            <div style="background: #d4edda; border-left: 4px solid #28a745; padding: 15px; margin-top: 20px;">
                <h4 style="margin: 0 0 5px 0; color: #155724;">Action Required</h4>
                <p style="margin: 0; color: #155724;">
                    The client did NOT receive any error message. Please investigate and respond manually if needed.
                </p>
            </div>

            <hr style="border: none; border-top: 1px solid #e9ecef; margin: 20px 0;">

            <p style="color: #6c757d; font-size: 12px; text-align: center; margin: 0;">
                OpenEvent AI Error Alert System<br>
                This email was sent because error alerting is enabled for this venue.
            </p>
        </div>
    </body>
    </html>
    """
    return html


def _build_error_alert_plain(
    error_type: str,
    error_message: str,
    client_email: str,
    client_name: str,
    original_message: str,
    workflow_step: Optional[str] = None,
    event_id: Optional[str] = None,
    stack_trace: Optional[str] = None,
    additional_context: Optional[Dict[str, Any]] = None,
) -> str:
    """Build plain text email for error alert."""
    venue_name = get_venue_name()
    tz = ZoneInfo(get_timezone())
    timestamp = datetime.now(tz).strftime("%Y-%m-%d %H:%M:%S %Z")

    text = f"""
WORKFLOW ERROR ALERT
====================
{venue_name} - {timestamp}

ERROR: {error_type}
{error_message}

CLIENT INFORMATION
------------------
Name: {client_name}
Email: {client_email}
Event ID: {event_id or 'N/A'}
Step: {workflow_step or 'Unknown'}

ORIGINAL CLIENT MESSAGE
-----------------------
{original_message}
"""

    if additional_context:
        text += "\nADDITIONAL CONTEXT\n------------------\n"
        for k, v in additional_context.items():
            text += f"  {k}: {v}\n"

    if stack_trace:
        text += f"\nSTACK TRACE\n-----------\n{stack_trace}\n"

    text += """
ACTION REQUIRED
---------------
The client did NOT receive any error message.
Please investigate and respond manually if needed.
"""
    return text


# =============================================================================
# Send Alert
# =============================================================================

def send_error_alert(
    error_type: str,
    error_message: str,
    client_email: str,
    client_name: str = "Unknown",
    original_message: str = "",
    workflow_step: Optional[str] = None,
    event_id: Optional[str] = None,
    exception: Optional[Exception] = None,
    additional_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Send error alert email to configured admin addresses.

    Args:
        error_type: Type of error (e.g., "Workflow Failure", "LLM Error")
        error_message: Human-readable error description
        client_email: Client's email address
        client_name: Client's name
        original_message: The message that triggered the error
        workflow_step: Current workflow step (e.g., "Step 3 - Room Availability")
        event_id: Event ID if available
        exception: The exception object for stack trace
        additional_context: Any additional debugging info

    Returns:
        Result dict with success status
    """
    config = get_error_alerting_config()

    if not config["enabled"]:
        logger.info("[ERROR_ALERT] Alerting disabled, skipping")
        return {"success": False, "error": "Error alerting not enabled"}

    if not config["alert_emails"]:
        logger.warning("[ERROR_ALERT] No alert emails configured")
        return {"success": False, "error": "No alert emails configured"}

    if not config["smtp_user"] or not config["smtp_password"]:
        logger.warning("[ERROR_ALERT] SMTP not configured, cannot send alert")
        return {"success": False, "error": "SMTP not configured"}

    # Get stack trace if exception provided
    stack_trace = None
    if exception:
        stack_trace = "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))

    try:
        venue_name = get_venue_name()
        subject = f"[OpenEvent Error] {error_type} - {client_email}"

        html_body = _build_error_alert_html(
            error_type=error_type,
            error_message=error_message,
            client_email=client_email,
            client_name=client_name,
            original_message=original_message,
            workflow_step=workflow_step,
            event_id=event_id,
            stack_trace=stack_trace,
            additional_context=additional_context,
        )

        plain_body = _build_error_alert_plain(
            error_type=error_type,
            error_message=error_message,
            client_email=client_email,
            client_name=client_name,
            original_message=original_message,
            workflow_step=workflow_step,
            event_id=event_id,
            stack_trace=stack_trace,
            additional_context=additional_context,
        )

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"{config['from_name']} <{config['from_email']}>"
        msg["To"] = ", ".join(config["alert_emails"])

        msg.attach(MIMEText(plain_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))

        # Send via SMTP
        with smtplib.SMTP(config["smtp_host"], config["smtp_port"]) as server:
            server.starttls()
            server.login(config["smtp_user"], config["smtp_password"])
            server.send_message(msg)

        logger.info(
            f"[ERROR_ALERT] Sent alert to {config['alert_emails']} for {error_type}"
        )

        return {
            "success": True,
            "message": f"Alert sent to {config['alert_emails']}",
            "recipients": config["alert_emails"],
        }

    except smtplib.SMTPException as e:
        logger.error(f"[ERROR_ALERT] SMTP error: {e}")
        return {"success": False, "error": f"SMTP error: {str(e)}"}
    except Exception as e:
        logger.error(f"[ERROR_ALERT] Failed to send: {e}")
        return {"success": False, "error": str(e)}


# =============================================================================
# Convenience Functions
# =============================================================================

def alert_workflow_error(
    error: Exception,
    client_email: str,
    client_name: str = "Unknown",
    original_message: str = "",
    workflow_step: Optional[str] = None,
    event_id: Optional[str] = None,
    **extra_context,
) -> Dict[str, Any]:
    """
    Convenience function to alert on workflow exceptions.

    Usage:
        try:
            process_workflow(...)
        except Exception as e:
            alert_workflow_error(
                error=e,
                client_email="client@example.com",
                workflow_step="Step 3",
            )
    """
    return send_error_alert(
        error_type="Workflow Error",
        error_message=str(error),
        client_email=client_email,
        client_name=client_name,
        original_message=original_message,
        workflow_step=workflow_step,
        event_id=event_id,
        exception=error,
        additional_context=extra_context or None,
    )


def alert_fallback_triggered(
    reason: str,
    client_email: str,
    client_name: str = "Unknown",
    original_message: str = "",
    workflow_step: Optional[str] = None,
    event_id: Optional[str] = None,
    **extra_context,
) -> Dict[str, Any]:
    """
    Alert when a fallback path is triggered.

    This is called when the workflow would normally send a
    "we'll get back to you" fallback message.
    """
    return send_error_alert(
        error_type="Fallback Triggered",
        error_message=reason,
        client_email=client_email,
        client_name=client_name,
        original_message=original_message,
        workflow_step=workflow_step,
        event_id=event_id,
        exception=None,
        additional_context=extra_context or None,
    )


# =============================================================================
# Startup Validation
# =============================================================================

def validate_alerting_config_on_startup() -> Dict[str, Any]:
    """
    Validate alerting configuration at application startup.

    CRITICAL: In production, if fallback suppression is enabled but alerting
    is not properly configured, errors will silently disappear. This check
    ensures that production deployments have proper error visibility.

    Call this from your application startup (e.g., in main.py or a startup event).

    Returns:
        Dict with:
            - valid: bool - True if config is valid for current environment
            - warnings: list[str] - Any configuration warnings
            - suppression_disabled: bool - True if suppression was disabled due to config issues
    """
    global _ALERTING_VALIDATED, _ALERTING_DISABLED_SUPPRESSION

    warnings = []
    suppression_disabled = False

    from backend.core.fallback import SUPPRESS_FALLBACK_IN_PRODUCTION

    # Check if we're in production mode with suppression enabled
    if SUPPRESS_FALLBACK_IN_PRODUCTION:
        config = get_error_alerting_config()

        # Check if alerting is enabled
        if not config["enabled"]:
            msg = (
                "CRITICAL: Fallback suppression is ON but error alerting is DISABLED. "
                "Errors will silently disappear! Enable alerting or disable suppression."
            )
            warnings.append(msg)
            logger.critical(msg)
            suppression_disabled = True

        # Check if alert emails are configured
        elif not config["alert_emails"]:
            msg = (
                "CRITICAL: Fallback suppression is ON but no alert emails configured. "
                "Errors will silently disappear! Add alert_emails in config."
            )
            warnings.append(msg)
            logger.critical(msg)
            suppression_disabled = True

        # Check if SMTP is configured
        elif not config["smtp_user"] or not config["smtp_password"]:
            msg = (
                "CRITICAL: Fallback suppression is ON but SMTP not configured. "
                "Alerts cannot be sent. Configure SMTP or disable suppression."
            )
            warnings.append(msg)
            logger.critical(msg)
            suppression_disabled = True

        else:
            logger.info(
                "[STARTUP] Error alerting validated: alerts will be sent to %s",
                config["alert_emails"],
            )

    else:
        # Dev/test mode - suppression not active
        logger.info("[STARTUP] Error alerting: suppression disabled (dev mode)")

    _ALERTING_VALIDATED = True
    _ALERTING_DISABLED_SUPPRESSION = suppression_disabled

    # If suppression was disabled due to config issues, update the fallback module
    if suppression_disabled:
        logger.warning(
            "[STARTUP] Disabling fallback suppression due to missing alerting config"
        )
        # Note: We can't actually modify SUPPRESS_FALLBACK_IN_PRODUCTION at runtime
        # since it's a module-level constant. Instead, we expose this flag for
        # the caller to handle appropriately (e.g., refuse to start, or log loudly).

    return {
        "valid": not suppression_disabled,
        "warnings": warnings,
        "suppression_disabled": suppression_disabled,
        "alerting_enabled": is_error_alerting_enabled(),
    }


def is_alerting_validated() -> bool:
    """Check if startup validation has been performed."""
    return _ALERTING_VALIDATED


def was_suppression_disabled() -> bool:
    """Check if suppression was disabled due to alerting config issues."""
    return _ALERTING_DISABLED_SUPPRESSION
