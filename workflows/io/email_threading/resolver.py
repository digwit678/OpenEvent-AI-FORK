"""Layer 2: Thread Resolver (LLM-based semantic matching).

This module handles NEW emails (not replies) by using LLM to semantically
compare the message against existing events for the same client. It:

1. Selects candidate events for the client (recent, active)
2. Asks LLM to compare message content vs event signatures
3. Applies hard constraints (date conflicts, etc.)
4. Returns decision with confidence score

Only called when Layer 1 (reply detection) cannot resolve the thread.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from .models import EventSignature, ResolutionResult

logger = logging.getLogger(__name__)

# Confidence threshold for attachment decision
# Below this, we create a new event but flag possible duplicates
CONFIDENCE_THRESHOLD = 0.85

# Maximum candidates to consider (to limit LLM cost)
MAX_CANDIDATES = 5

# How far back to look for candidate events (days)
CANDIDATE_WINDOW_DAYS = 60


class ThreadResolver:
    """LLM-based thread resolver for new emails.

    Determines whether a new email should be attached to an existing
    event or create a new one, using semantic comparison.
    """

    def __init__(self, llm_client: Optional[Any] = None):
        """Initialize resolver.

        Args:
            llm_client: Optional LLM client for semantic matching.
                If None, uses the default workflow LLM.
        """
        self._llm_client = llm_client

    def resolve(
        self,
        email_from: str,
        email_subject: str,
        email_body: str,
        db: Dict[str, Any],
        message_id: Optional[str] = None,
    ) -> ResolutionResult:
        """Resolve thread for a new email.

        This is the main entry point for Layer 2 resolution. Called only
        for emails that are not replies (Layer 1 returned is_reply=False).

        Args:
            email_from: Sender email address
            email_subject: Email subject line
            email_body: Email body text
            db: The database dict
            message_id: Optional Message-ID for logging

        Returns:
            ResolutionResult with decision and confidence
        """
        email_lc = (email_from or "").lower()

        # Step A: Get candidate events for this client
        candidates = self._select_candidates(email_lc, db)

        if not candidates:
            logger.debug("[THREAD][L2] No candidate events for %s - creating new", email_lc)
            return ResolutionResult(
                decision="new_event",
                confidence=1.0,
                reason="no_existing_events_for_client",
            )

        # Step B: LLM semantic comparison
        llm_result = self._semantic_match(
            email_subject=email_subject,
            email_body=email_body,
            candidates=candidates,
        )

        # Step C: Hard constraint validation
        if llm_result.decision == "attach" and llm_result.event_id:
            if self._has_date_conflict(email_body, llm_result.event_id, db):
                logger.info(
                    "[THREAD][L2] Date conflict detected for event %s - creating new",
                    llm_result.event_id
                )
                return ResolutionResult(
                    decision="new_event",
                    confidence=0.9,
                    possible_duplicates=[llm_result.event_id],
                    reason="date_conflict_detected",
                )

        # Step D: Apply confidence threshold
        if llm_result.decision == "attach" and llm_result.confidence < CONFIDENCE_THRESHOLD:
            logger.info(
                "[THREAD][L2] Confidence %.2f below threshold %.2f for event %s",
                llm_result.confidence, CONFIDENCE_THRESHOLD, llm_result.event_id
            )
            return ResolutionResult(
                decision="new_event",
                possible_duplicates=[llm_result.event_id] if llm_result.event_id else [],
                confidence=llm_result.confidence,
                reason="confidence_below_threshold",
            )

        logger.info(
            "[THREAD][L2] Resolved: %s (event=%s, confidence=%.2f)",
            llm_result.decision, llm_result.event_id, llm_result.confidence
        )
        return llm_result

    def _select_candidates(
        self,
        client_email: str,
        db: Dict[str, Any],
        max_candidates: int = MAX_CANDIDATES,
        recent_days: int = CANDIDATE_WINDOW_DAYS,
    ) -> List[Dict[str, Any]]:
        """Select candidate events for a client.

        Filters events by:
        - Same client email
        - Not in terminal state (cancelled, completed)
        - Created within recent window

        Args:
            client_email: Client email address (lowercase)
            db: The database dict
            max_candidates: Maximum number to return
            recent_days: How far back to look

        Returns:
            List of candidate event dicts, most recent first
        """
        candidates: List[Dict[str, Any]] = []
        cutoff_date = (datetime.now(timezone.utc) - timedelta(days=recent_days)).isoformat()

        for event in db.get("events", []):
            event_data = event.get("event_data", {})
            event_email = (event_data.get("Email") or "").lower()

            # Must be same client
            if event_email != client_email:
                continue

            # Skip terminal states
            status = (event.get("status") or "").lower()
            if status in ("cancelled", "completed"):
                continue

            # Skip very old events
            created_at = event.get("created_at", "")
            if created_at and created_at < cutoff_date:
                continue

            candidates.append(event)

        # Sort by created_at descending (most recent first)
        candidates.sort(key=lambda e: e.get("created_at", ""), reverse=True)

        return candidates[:max_candidates]

    def _semantic_match(
        self,
        email_subject: str,
        email_body: str,
        candidates: List[Dict[str, Any]],
    ) -> ResolutionResult:
        """Use LLM to semantically match email to candidates.

        Builds a prompt comparing the email content against event signatures
        and asks the LLM to determine the best match.

        Args:
            email_subject: Email subject
            email_body: Email body
            candidates: List of candidate events

        Returns:
            ResolutionResult from LLM analysis
        """
        # Build event signatures for comparison
        signatures = [EventSignature.from_event(e) for e in candidates]

        # Build prompt for LLM
        prompt = self._build_match_prompt(email_subject, email_body, signatures)

        # Call LLM
        try:
            llm_response = self._call_llm(prompt)
            return self._parse_llm_response(llm_response, candidates)
        except Exception as e:
            logger.warning("[THREAD][L2] LLM call failed: %s - defaulting to new_event", e)
            return ResolutionResult(
                decision="new_event",
                confidence=0.5,
                reason=f"llm_error: {e}",
            )

    def _build_match_prompt(
        self,
        email_subject: str,
        email_body: str,
        signatures: List[EventSignature],
    ) -> str:
        """Build LLM prompt for semantic matching."""
        # Format event summaries
        event_summaries = []
        for i, sig in enumerate(signatures, 1):
            summary_parts = [f"Event {i} (ID: {sig.event_id}):"]
            if sig.date_range:
                date_str = sig.date_range.get("start", "unknown")
                if sig.date_range.get("end") and sig.date_range["end"] != sig.date_range.get("start"):
                    date_str += f" to {sig.date_range['end']}"
                summary_parts.append(f"  - Date: {date_str}")
            if sig.room_or_location:
                summary_parts.append(f"  - Room/Location: {sig.room_or_location}")
            if sig.participant_count:
                summary_parts.append(f"  - Participants: {sig.participant_count}")
            if sig.event_type:
                summary_parts.append(f"  - Event Type: {sig.event_type}")
            event_summaries.append("\n".join(summary_parts))

        events_text = "\n\n".join(event_summaries)

        return f"""You are analyzing an incoming email to determine if it relates to an existing event booking.

## Incoming Email
Subject: {email_subject}
Body:
{email_body[:1500]}

## Existing Events for this Client
{events_text}

## Task
Determine if this email is about one of the existing events or a completely new inquiry.

Consider:
- Does the email mention dates, rooms, or details matching an event?
- Is this a follow-up question about an existing booking?
- Is this a completely new event request with different dates/details?

Respond in JSON format:
{{
  "decision": "attach" or "new_event",
  "event_id": "the event ID if attaching, null otherwise",
  "confidence": 0.0 to 1.0,
  "reason": "brief explanation"
}}

If uncertain, prefer "new_event" with lower confidence and include the possible event ID.
"""

    def _call_llm(self, prompt: str) -> str:
        """Call LLM with the prompt.

        Uses the injected client or falls back to workflow default.
        """
        if self._llm_client:
            return self._llm_client.complete(prompt)

        # Use workflow's LLM infrastructure via AgentAdapter
        from adapters.agent_adapter import get_agent_adapter
        agent = get_agent_adapter()
        return agent.complete(
            prompt,
            system_prompt="You are a thread resolution assistant. Analyze emails to determine if they relate to existing event bookings.",
            temperature=0.1,
            max_tokens=500,
            json_mode=True,
        )

    def _parse_llm_response(
        self,
        response: str,
        candidates: List[Dict[str, Any]],
    ) -> ResolutionResult:
        """Parse LLM response into ResolutionResult."""
        import json

        # Extract JSON from response
        try:
            # Handle potential markdown code blocks
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]

            data = json.loads(json_str.strip())
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning("[THREAD][L2] Failed to parse LLM response: %s", e)
            return ResolutionResult(
                decision="new_event",
                confidence=0.5,
                reason="llm_response_parse_error",
            )

        decision = data.get("decision", "new_event")
        event_id = data.get("event_id")
        confidence = float(data.get("confidence", 0.5))
        reason = data.get("reason", "")

        # Validate event_id if attaching
        if decision == "attach" and event_id:
            valid_ids = {c.get("event_id") for c in candidates}
            if event_id not in valid_ids:
                logger.warning("[THREAD][L2] LLM returned invalid event_id: %s", event_id)
                return ResolutionResult(
                    decision="new_event",
                    confidence=0.5,
                    reason="llm_returned_invalid_event_id",
                )

        return ResolutionResult(
            decision=decision,
            event_id=event_id if decision == "attach" else None,
            confidence=confidence,
            reason=reason,
        )

    def _has_date_conflict(
        self,
        email_body: str,
        event_id: str,
        db: Dict[str, Any],
    ) -> bool:
        """Check for hard date conflicts.

        Returns True if the email mentions a date that clearly conflicts
        with the event's confirmed date (not a change request, but a
        different event entirely).
        """
        # Find the event
        event = None
        for e in db.get("events", []):
            if e.get("event_id") == event_id:
                event = e
                break

        if not event:
            return False

        # Get event's confirmed date
        event_date = event.get("chosen_date")
        if not event_date or not event.get("date_confirmed"):
            # Date not confirmed - no conflict possible
            return False

        # Simple heuristic: if email explicitly mentions a different date
        # in a context suggesting a NEW event (not a change request)
        # This is a simplified check - the LLM already considers this
        # Here we just double-check obvious conflicts

        # For now, rely on LLM's assessment - this is a placeholder for
        # additional hard constraint logic if needed
        return False
