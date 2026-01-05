---

## 10. Multi-Tenancy Requirements

**Goal:** Transform the single-manager application into a platform supporting multiple independent managers/teams.
**Constraint:** Each manager must only see their own clients and events. Data must be strictly isolated.

### 10.1 Data Model Updates

Every major table requires a `team_id` (or `organization_id`) to enforce isolation.

**Required Schema Changes:**
```sql
-- Add team ownership to all core tables
ALTER TABLE events ADD COLUMN team_id UUID NOT NULL;
ALTER TABLE clients ADD COLUMN team_id UUID NOT NULL;
ALTER TABLE tasks ADD COLUMN team_id UUID NOT NULL;
ALTER TABLE messages ADD COLUMN team_id UUID NOT NULL;
ALTER TABLE site_visits ADD COLUMN team_id UUID NOT NULL;
ALTER TABLE deposits ADD COLUMN team_id UUID NOT NULL;
ALTER TABLE page_snapshots ADD COLUMN team_id UUID NOT NULL;

-- Reference Data (Rooms/Products) must also be team-scoped
-- (Managers define their OWN rooms and products)
ALTER TABLE rooms ADD COLUMN team_id UUID NOT NULL;
ALTER TABLE products ADD COLUMN team_id UUID NOT NULL;
ALTER TABLE offers ADD COLUMN team_id UUID NOT NULL;

-- Indexes for performance and filtering
CREATE INDEX idx_events_team ON events(team_id);
CREATE INDEX idx_clients_team ON clients(team_id);
```

### 10.2 Authentication & Context

The backend must identify the **Current Manager** from the request to know which `team_id` to use.

1.  **API Requests (Frontend/Chat):**
    *   Requests must include an Auth Token (e.g., Supabase JWT).
    *   Backend middleware extracts `user_id` and `team_id` from the token.
    *   This context is passed to the Database Adapter.

2.  **Email Ingestion (Mail Server):**
    *   **Challenge:** Incoming emails don't have a login token.
    *   **Solution:** We must map the **Ingestion Source** to the `team_id`.
    *   *Example:*
        *   Email to `events@hotel-a.com` -> routed to Team A.
        *   Email to `bookings@venue-b.com` -> routed to Team B.
    *   **Requirement:** The Mail Integration layer must resolve the destination email address (or mailbox ID) to the correct `team_id` BEFORE calling the workflow engine.

### 10.3 Integration Steps for Email Workflow

When integrating the "Mail Section" of the platform:

1.  **Binding:** You must associate each Manager's external email account (IMAP/SMTP/Gmail) with their Platform `team_id`.
2.  **Ingestion Loop:**
    *   Poll Manager A's inbox.
    *   For every new email:
        *   Extract: `From`, `Subject`, `Body`.
        *   **CRITICAL:** Inject `team_id = Manager A's ID` into the payload.
        *   Call Workflow Engine: `process_email(payload, context={team_id: ...})`.
3.  **Outbound:**
    *   When the workflow generates a reply, it looks up the Mail Server config for the specific `team_id`.
    *   Sends via Manager A's SMTP server.

### 10.4 Developer Plan
A detailed technical plan for enabling this feature is available in `docs/plans/active/MULTI_TENANT_EXPANSION_PLAN.md`.