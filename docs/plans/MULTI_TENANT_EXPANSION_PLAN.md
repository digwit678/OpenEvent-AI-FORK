# Multi-Tenant Expansion Plan

**Objective:** Upgrade the OpenEvent-AI backend to support multiple isolated tenants (Manager Teams). Each tenant has their own clients, events, rooms, and products.

---

## Phase 1: Context Propagation (The "Who is calling?" Layer)

Currently, the backend assumes a single global configuration. We need to inject "Request Context" into every database operation.

### 1.1 Context Object
Create a `WorkflowContext` class to hold the current execution scope.

```python
@dataclass
class WorkflowContext:
    team_id: str          # The tenant (Organization)
    user_id: Optional[str] # The specific user (Manager) or "system"
    source: str           # "api", "email", "job"
```

### 1.2 Context Manager / Middleware
*   **FastAPI Middleware:** Intercept every HTTP request.
    *   Parse the Authorization header (JWT).
    *   Extract `team_id` from the user's claims or profile.
    *   Store in a thread-local variable (e.g., using `contextvars`).
*   **Email Entry Point:**
    *   Update `process_msg` to accept a `team_id` argument.
    *   The email poller MUST provide this ID based on which mailbox received the message.

---

## Phase 2: Database Adapter Upgrades

The `supabase_adapter.py` currently reads `OE_TEAM_ID` from a global environment variable. This must be refactored to read from the dynamic `WorkflowContext`.

### 2.1 Refactor Adapter Signatures
Modify database functions to accept an optional context, or retrieve it from the global `contextvar`.

*   *Current:* `def upsert_client(email, ...)` -> Uses global `get_team_id()`
*   *New:* `def upsert_client(email, ..., ctx: WorkflowContext)` -> Uses `ctx.team_id`

### 2.2 Row Level Security (RLS) - The Safety Net
While the application *should* always filter by `team_id`, we must enforce it at the database level for security.

*   **Supabase Policy:**
    ```sql
    CREATE POLICY "Tenant Isolation" ON events
    USING (team_id = auth.jwt() ->> 'team_id');
    ```
    *(Note: This requires the JWT to contain the custom claim `team_id`)*

---

## Phase 3: Data Model Migration

We need to associate all existing "Reference Data" (Rooms, Products) with the correct tenant.

### 3.1 Migration Script
1.  **Rooms & Products:**
    *   Currently loaded from `rooms.json` or `catering_menu.json`.
    *   **Action:** Import these JSON files into Supabase `rooms` and `products` tables, tagging them with the `team_id` of the initial Admin/Manager.
2.  **Config:**
    *   Move global configs (Deposit settings, rules) to a `team_configs` table in Supabase.

---

## Phase 4: Email Workflow Integration (The Binding)

This is the critical link between the "Mail Server" and the "Application".

### 4.1 Mailbox Binding Table
We need a registry of connected email accounts.

```sql
CREATE TABLE email_accounts (
    account_id UUID PRIMARY KEY,
    team_id UUID REFERENCES teams(id),
    email_address TEXT NOT NULL,
    provider TEXT, -- 'gmail', 'outlook', 'smtp'
    credentials_ref TEXT, -- Reference to secure storage
    is_active BOOLEAN DEFAULT TRUE
);
```

### 4.2 Ingestion Routing Logic
The email ingestion worker needs to:
1.  Receive an incoming email (e.g., via Webhook or IMAP polling).
2.  Identify the **Recipient Address** (e.g., `events@hotel-zuerich.com`).
3.  Look up `email_accounts` to find the matching `team_id`.
4.  **Fail-safe:** If no match found, route to a "System Admin" or "Unassigned" queue.
5.  Call the OpenEvent Backend:
    ```json
    POST /api/webhooks/email
    {
      "team_id": "uuid-of-hotel-zuerich",
      "from": "client@example.com",
      "body": "..."
    }
    ```

---

## Phase 5: Testing Strategy

### 5.1 Multi-Tenant Test Case
1.  Create Team A and Team B.
2.  Create "Room A" for Team A and "Room B" for Team B.
3.  **Test 1 (Isolation):** Login as Team A manager. Verify `list_rooms` ONLY returns "Room A".
4.  **Test 2 (Client Collision):**
    *   Client `john@doe.com` emails Team A. (Should create Client Profile linked to Team A).
    *   Client `john@doe.com` emails Team B. (Should create a **separate** Client Profile linked to Team B).
    *   *Verify:* Team A's notes on John are NOT visible to Team B.

### 5.2 Implementation Checklist
- [ ] Add `WorkflowContext` using `contextvars`.
- [ ] Update `supabase_adapter.py` to use context `team_id`.
- [ ] Add `team_id` column to all Supabase tables.
- [ ] Create RLS policies on Supabase.
- [ ] Implement `email_accounts` table for routing.
- [ ] Update `/api/webhooks/email` to require `team_id`.
