-- =============================================================================
-- Multi-Tenancy RLS Policies for Team Isolation
-- Created: 2026-01-03
-- =============================================================================
--
-- This migration enables Row-Level Security (RLS) on all tenant-scoped tables
-- and creates policies to ensure data isolation between teams.
--
-- The backend sets the team context via:
--   SET LOCAL app.team_id = '<team_id>';
-- before executing queries when using authenticated connections.
--
-- Service role connections bypass RLS entirely.
-- =============================================================================

-- =============================================================================
-- STEP 1: Enable RLS on all tenant-scoped tables
-- =============================================================================

ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE events ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE emails ENABLE ROW LEVEL SECURITY;
ALTER TABLE rooms ENABLE ROW LEVEL SECURITY;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE offers ENABLE ROW LEVEL SECURITY;
ALTER TABLE offer_line_items ENABLE ROW LEVEL SECURITY;

-- =============================================================================
-- STEP 2: Create team isolation policies
-- =============================================================================
-- Each policy restricts access to rows where team_id matches the session setting.
-- The `true` parameter in current_setting makes it return NULL if not set,
-- preventing errors but also preventing access when no team context is set.

-- Clients table
CREATE POLICY "team_isolation_clients" ON clients
    FOR ALL
    USING (team_id::text = current_setting('app.team_id', true));

-- Events table
CREATE POLICY "team_isolation_events" ON events
    FOR ALL
    USING (team_id::text = current_setting('app.team_id', true));

-- Tasks table (HIL tasks)
CREATE POLICY "team_isolation_tasks" ON tasks
    FOR ALL
    USING (team_id::text = current_setting('app.team_id', true));

-- Emails table
CREATE POLICY "team_isolation_emails" ON emails
    FOR ALL
    USING (team_id::text = current_setting('app.team_id', true));

-- Rooms table
CREATE POLICY "team_isolation_rooms" ON rooms
    FOR ALL
    USING (team_id::text = current_setting('app.team_id', true));

-- Products table
CREATE POLICY "team_isolation_products" ON products
    FOR ALL
    USING (team_id::text = current_setting('app.team_id', true));

-- Offers table
CREATE POLICY "team_isolation_offers" ON offers
    FOR ALL
    USING (team_id::text = current_setting('app.team_id', true));

-- Offer line items table
CREATE POLICY "team_isolation_offer_line_items" ON offer_line_items
    FOR ALL
    USING (team_id::text = current_setting('app.team_id', true));

-- =============================================================================
-- STEP 3: Service role bypass policies
-- =============================================================================
-- The service role (used by backend) needs full access to all rows.
-- These policies grant unrestricted access to the service_role.

CREATE POLICY "service_role_full_access_clients" ON clients
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_full_access_events" ON events
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_full_access_tasks" ON tasks
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_full_access_emails" ON emails
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_full_access_rooms" ON rooms
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_full_access_products" ON products
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_full_access_offers" ON offers
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

CREATE POLICY "service_role_full_access_offer_line_items" ON offer_line_items
    FOR ALL
    TO service_role
    USING (true)
    WITH CHECK (true);

-- =============================================================================
-- STEP 4: Create indexes for team_id (performance optimization)
-- =============================================================================
-- These indexes improve query performance when filtering by team_id.

CREATE INDEX IF NOT EXISTS idx_clients_team_id ON clients(team_id);
CREATE INDEX IF NOT EXISTS idx_events_team_id ON events(team_id);
CREATE INDEX IF NOT EXISTS idx_tasks_team_id ON tasks(team_id);
CREATE INDEX IF NOT EXISTS idx_emails_team_id ON emails(team_id);
CREATE INDEX IF NOT EXISTS idx_rooms_team_id ON rooms(team_id);
CREATE INDEX IF NOT EXISTS idx_products_team_id ON products(team_id);
CREATE INDEX IF NOT EXISTS idx_offers_team_id ON offers(team_id);
CREATE INDEX IF NOT EXISTS idx_offer_line_items_team_id ON offer_line_items(team_id);

-- =============================================================================
-- NOTES FOR DEPLOYMENT
-- =============================================================================
--
-- Before running this migration in production:
--
-- 1. Ensure all tables have a `team_id` column (UUID type recommended)
-- 2. Backfill any NULL team_id values with the correct team
-- 3. Run this migration during a maintenance window
-- 4. Test with both service_role and authenticated connections
--
-- To set team context for non-service-role queries:
--   SET LOCAL app.team_id = 'your-team-uuid-here';
--
-- To verify RLS is working:
--   SELECT current_setting('app.team_id', true);
--   SELECT * FROM clients; -- Should only return matching team's clients
-- =============================================================================
