-- ============================================================================
-- CloudScale Inc. B2B SaaS Platform Database Schema
-- Dialect: SQLite 3
-- Description: Core schema supporting customer management, subscription billing,
--              and operational incident tracking with foreign keys and indexes.
-- ============================================================================

PRAGMA foreign_keys = ON;

-- Drop existing tables if recreating schema
DROP TABLE IF EXISTS incident_tickets;
DROP TABLE IF EXISTS subscriptions;
DROP TABLE IF EXISTS customers;

-- ============================================================================
-- 1. Customers Table
-- Stores tenant profiles, tiering, geographical regions, and account lifecycle status.
-- ============================================================================
CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_name TEXT NOT NULL,
    tier TEXT NOT NULL CHECK (tier IN ('Starter', 'Professional', 'Enterprise')),
    region TEXT NOT NULL CHECK (region IN ('North America', 'Europe', 'Asia Pacific', 'Latin America')),
    contact_email TEXT NOT NULL UNIQUE,
    joined_date TEXT NOT NULL CHECK (joined_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    status TEXT NOT NULL CHECK (status IN ('active', 'suspended', 'churned'))
);

-- ============================================================================
-- 2. Subscriptions Table
-- Tracks recurring subscription plans, contracted monthly rates, billing cadences,
-- and real-time payment collection statuses.
-- ============================================================================
CREATE TABLE subscriptions (
    subscription_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    plan_name TEXT NOT NULL,
    billing_cycle TEXT NOT NULL CHECK (billing_cycle IN ('monthly', 'annual')),
    monthly_rate REAL NOT NULL CHECK (monthly_rate >= 0),
    start_date TEXT NOT NULL CHECK (start_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    renewal_date TEXT NOT NULL CHECK (renewal_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    payment_status TEXT NOT NULL CHECK (payment_status IN ('paid', 'pending', 'overdue')),
    FOREIGN KEY (customer_id) REFERENCES customers (customer_id) ON DELETE CASCADE
);

-- ============================================================================
-- 3. Incident Tickets Table
-- Operational issue tracker recording production severity levels, customer downtime,
-- lifecycle timestamps, and SLA breach indicators.
-- ============================================================================
CREATE TABLE incident_tickets (
    ticket_id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('Severity 1', 'Severity 2', 'Severity 3')),
    downtime_minutes INTEGER NOT NULL DEFAULT 0 CHECK (downtime_minutes >= 0),
    reported_at TEXT NOT NULL,
    resolved_at TEXT,
    status TEXT NOT NULL CHECK (status IN ('resolved', 'in_progress', 'closed')),
    sla_breached INTEGER NOT NULL DEFAULT 0 CHECK (sla_breached IN (0, 1)),
    FOREIGN KEY (customer_id) REFERENCES customers (customer_id) ON DELETE CASCADE
);

-- ============================================================================
-- Indexes for Performance Optimization & Fast Lookups
-- ============================================================================

-- Customers indexing for segmentation by tier, region, and account status
CREATE INDEX idx_customers_tier ON customers (tier);
CREATE INDEX idx_customers_region ON customers (region);
CREATE INDEX idx_customers_status ON customers (status);
CREATE INDEX idx_customers_tier_region_status ON customers (tier, region, status);

-- Subscriptions indexing for foreign key joins, billing cycle, and payment monitoring
CREATE INDEX idx_subscriptions_customer_id ON subscriptions (customer_id);
CREATE INDEX idx_subscriptions_payment_status ON subscriptions (payment_status);
CREATE INDEX idx_subscriptions_renewal_date ON subscriptions (renewal_date);
CREATE INDEX idx_subscriptions_monthly_rate ON subscriptions (monthly_rate);

-- Incident tickets indexing for support metrics, severity routing, and SLA compliance
CREATE INDEX idx_incident_tickets_customer_id ON incident_tickets (customer_id);
CREATE INDEX idx_incident_tickets_severity ON incident_tickets (severity);
CREATE INDEX idx_incident_tickets_status ON incident_tickets (status);
CREATE INDEX idx_incident_tickets_sla_breached ON incident_tickets (sla_breached);
