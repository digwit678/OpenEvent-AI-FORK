# Email Threading Module

This module provides **two-layer email thread resolution** that runs BEFORE workflow processing to route inbound emails to the correct event.

## Architecture

```
Inbound Email
     │
     ▼
┌─────────────────────────────────────┐
│  LAYER 1: Reply Detection (NO LLM) │
│  ─────────────────────────────────  │
│  Check email headers:               │
│  • In-Reply-To header exists?       │
│  • References header chain?         │
│  • Explicit OE token in footer?     │
│                                     │
│  If YES → Link to known thread      │
│  If NO  → Proceed to Layer 2        │
└─────────────────────────────────────┘
     │
     │ (Only for NEW emails)
     ▼
┌─────────────────────────────────────┐
│  LAYER 2: Thread Resolver (LLM)    │
│  ─────────────────────────────────  │
│  • Build candidate events for client│
│  • LLM compares message vs events   │
│  • Apply confidence threshold (0.85)│
│  • Decision: attach or new_event    │
└─────────────────────────────────────┘
```

## Key Principle

**Layer 1 makes ZERO LLM calls.** It uses RFC 5322 email protocol headers for deterministic reply detection:

- `In-Reply-To`: Direct parent message reference
- `References`: Chain of ancestor messages
- `[OE-xxxxxxxx]`: Custom tracking token in email body/footer

Only when Layer 1 cannot resolve (new emails without headers) does Layer 2 call the LLM.

## Files

| File | Purpose |
|------|---------|
| `__init__.py` | Module exports |
| `models.py` | Data models: EmailMessage, ThreadMapping, ResolutionResult |
| `reply_detector.py` | Layer 1: Header-based reply detection (NO LLM) |
| `resolver.py` | Layer 2: LLM-based semantic matching |

## API Integration

### HTTP Endpoints

Both `/api/start-conversation` and `/api/send-message` accept optional `email_headers`:

```json
POST /api/start-conversation
{
  "email_body": "Quick question about March workshop...",
  "client_email": "sarah@corp.com",
  "email_headers": {
    "message_id": "<msg-123@client.com>",
    "in_reply_to": "<orig-001@venue.com>",
    "references": ["<thread-start@venue.com>", "<orig-001@venue.com>"]
  }
}
```

### Python Usage

```python
from workflows.io.email_threading import (
    is_reply,
    link_reply_to_thread,
    store_email_message,
    ThreadResolver,
)

# Layer 1: Check if email is a reply
headers = {
    "In-Reply-To": "<parent-msg@example.com>",
    "body": "Thanks for the info!",
}
is_reply_msg, parent_id = is_reply(headers)

if is_reply_msg:
    # Link to existing event via stored messages
    event_id = link_reply_to_thread(
        parent_id,
        db["email_messages"],
        db["thread_mappings"],
    )
else:
    # Layer 2: LLM-based resolution for new emails
    resolver = ThreadResolver()
    result = resolver.resolve(
        email_from="sarah@corp.com",
        email_subject="Question about workshop",
        email_body="For our March 15th workshop...",
        db=db,
    )
    if result.decision == "attach":
        event_id = result.event_id
```

## Database Collections

The module adds three collections to the database schema:

```python
db["email_messages"] = [
    {
        "message_id": "msg-123@client.com",
        "from_address": "sarah@corp.com",
        "in_reply_to": "orig-001@venue.com",
        "references": ["thread-start@venue.com"],
        "resolved_event_id": "evt-001",
        "created_at": "2026-01-15T10:00:00Z",
    }
]

db["thread_mappings"] = [
    {
        "email_thread_id": "msg-123@client.com",
        "event_id": "evt-001",
        "created_at": "2026-01-15T10:00:00Z",
    }
]

db["event_signatures"] = []  # Reserved for future LLM-derived summaries
```

## Integration Point

The threading module is called in `workflows/steps/step1_intake/trigger/event_bootstrap.py`:

```python
def ensure_event_record(state, message_payload, user_info):
    # NEW: Thread resolution for email messages
    if _has_email_headers(message_payload):
        event_entry, resolved = _resolve_email_thread(
            state, message_payload, thread_id
        )
        if resolved:
            return event_entry

    # Fall through to existing logic...
```

## Testing

```bash
# Run all threading tests
pytest tests/email_threading/ -v

# Run with verbose output to see Layer 1 vs Layer 2 behavior
pytest tests/email_threading/test_flow_verification.py -v -s

# Run with real LLM (requires RUN_REAL_LLM_TESTS=1)
RUN_REAL_LLM_TESTS=1 pytest tests/email_threading/test_real_llm_integration.py -v
```

## Test Coverage

| Test File | Coverage |
|-----------|----------|
| `test_reply_detector.py` | Layer 1: 20 tests |
| `test_resolver.py` | Layer 2: 14 tests |
| `test_real_llm_integration.py` | Integration: Verifies LLM is NOT called for Layer 1 |
| `test_flow_verification.py` | End-to-end: Shows both layers working together |

## Confidence Threshold

Layer 2 uses a confidence threshold of **0.85**:

- `confidence >= 0.85` → Attach to existing event
- `confidence < 0.85` → Create new event, tag `possible_duplicates` for manual review

This prevents false positives while flagging uncertain cases.
