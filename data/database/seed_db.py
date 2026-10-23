#!/usr/bin/env python3
"""
CloudScale Inc. B2B SaaS Platform Database Seeding & Verification Script

This script initializes the SQLite database (app.db), enforces foreign key
integrity, applies schema definitions and realistic seed data, validates
row counts, and runs demonstration queries covering filtering, aggregations,
multi-table joins, and business metric calculations.
"""

import sqlite3
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "app.db"
SCHEMA_PATH = BASE_DIR / "schema.sql"
SEED_PATH = BASE_DIR / "seed_data.sql"


def format_table(headers, rows):
    """Utility to format tabular output cleanly."""
    str_rows = [[str(cell) if cell is not None else "NULL" for cell in row] for row in rows]
    col_widths = [len(h) for h in headers]
    for row in str_rows:
        for idx, cell in enumerate(row):
            col_widths[idx] = max(col_widths[idx], len(cell))

    sep = "+-" + "-+-".join("-" * w for w in col_widths) + "-+"
    header_str = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers)) + " |"

    lines = [sep, header_str, sep]
    for row in str_rows:
        row_str = "| " + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(row)) + " |"
        lines.append(row_str)
    lines.append(sep)
    return "\n".join(lines)


def init_database():
    """Initializes schema and loads seed data into SQLite database."""
    print("=" * 80)
    print("CloudScale Inc. Database Seeder & Validator")
    print("=" * 80)
    print(f"Database Path : {DB_PATH}")
    print(f"Schema Path   : {SCHEMA_PATH}")
    print(f"Seed Data Path: {SEED_PATH}\n")

    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found at {SCHEMA_PATH}")
    if not SEED_PATH.exists():
        raise FileNotFoundError(f"Seed file not found at {SEED_PATH}")

    # Remove existing database file if present to guarantee clean slate
    if DB_PATH.exists():
        DB_PATH.unlink()
        print("Removed existing app.db for fresh initialization.")

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Enable foreign keys constraint enforcement
    cursor.execute("PRAGMA foreign_keys = ON;")
    fk_status = cursor.execute("PRAGMA foreign_keys;").fetchone()[0]
    print(f"PRAGMA foreign_keys enabled: {bool(fk_status)}")

    # Execute schema
    print("Applying schema.sql...")
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        schema_sql = f.read()
    cursor.executescript(schema_sql)
    print("Schema applied successfully.")

    # Execute seed data
    print("Applying seed_data.sql...")
    with open(SEED_PATH, encoding="utf-8") as f:
        seed_sql = f.read()
    cursor.executescript(seed_sql)
    conn.commit()
    print("Seed data applied successfully.\n")

    return conn


def validate_records(conn):
    """Validates row counts across all database tables."""
    print("-" * 80)
    print("TABLE ROW COUNT VALIDATION")
    print("-" * 80)

    tables = ["customers", "subscriptions", "incident_tickets"]
    cursor = conn.cursor()
    counts = {}

    for table in tables:
        count = cursor.execute(f"SELECT COUNT(*) FROM {table};").fetchone()[0]
        counts[table] = count
        print(f"Table '{table}' row count: {count}")

    # Assertions
    assert counts["customers"] >= 25, f"Expected >= 25 customers, found {counts['customers']}"
    assert (
        counts["subscriptions"] >= 25
    ), f"Expected >= 25 subscriptions, found {counts['subscriptions']}"
    assert (
        counts["incident_tickets"] >= 15
    ), f"Expected >= 15 incident tickets, found {counts['incident_tickets']}"
    print("All row count assertions PASSED.\n")
    return counts


def run_sample_queries(conn):
    """Executes sample analytical and operational queries against the database."""
    cursor = conn.cursor()

    # Query 1: Filtering Query
    # Active Enterprise customers located in Europe
    print("-" * 80)
    print("QUERY 1 (FILTERING): Active Enterprise Customers in Europe")
    print("-" * 80)
    q1 = """
    SELECT
        customer_id,
        company_name,
        tier,
        region,
        contact_email,
        joined_date,
        status
    FROM customers
    WHERE tier = 'Enterprise'
      AND region = 'Europe'
      AND status = 'active'
    ORDER BY customer_id;
    """
    cursor.execute(q1)
    rows_q1 = cursor.fetchall()
    headers_q1 = ["ID", "Company Name", "Tier", "Region", "Contact Email", "Joined Date", "Status"]
    print(format_table(headers_q1, rows_q1))
    print(f"Returned {len(rows_q1)} records.\n")

    # Query 2: Aggregation Query
    # Total subscriptions, total monthly revenue, and average rate grouped by tier
    print("-" * 80)
    print("QUERY 2 (AGGREGATION): Subscription Metrics by Customer Tier")
    print("-" * 80)
    q2 = """
    SELECT
        c.tier,
        COUNT(s.subscription_id) AS total_subscriptions,
        PRINTF('$%.2f', SUM(s.monthly_rate)) AS total_monthly_revenue,
        PRINTF('$%.2f', AVG(s.monthly_rate)) AS avg_monthly_rate,
        PRINTF('$%.2f', MIN(s.monthly_rate)) AS min_monthly_rate,
        PRINTF('$%.2f', MAX(s.monthly_rate)) AS max_monthly_rate
    FROM customers c
    JOIN subscriptions s ON c.customer_id = s.customer_id
    GROUP BY c.tier
    ORDER BY SUM(s.monthly_rate) DESC;
    """
    cursor.execute(q2)
    rows_q2 = cursor.fetchall()
    headers_q2 = ["Tier", "Subscriptions", "Total MRR", "Avg Monthly Rate", "Min Rate", "Max Rate"]
    print(format_table(headers_q2, rows_q2))
    print(f"Returned {len(rows_q2)} groups.\n")

    # Query 3: Multi-table Join Query
    # Top 5 customers by monthly subscription rate
    print("-" * 80)
    print("QUERY 3 (JOIN): Top 5 Customers by Monthly Subscription Rate")
    print("-" * 80)
    q3 = """
    SELECT
        c.customer_id,
        c.company_name,
        c.tier,
        c.region,
        s.plan_name,
        s.billing_cycle,
        PRINTF('$%.2f', s.monthly_rate) AS monthly_rate,
        s.payment_status
    FROM customers c
    JOIN subscriptions s ON c.customer_id = s.customer_id
    ORDER BY s.monthly_rate DESC, c.company_name ASC
    LIMIT 5;
    """
    cursor.execute(q3)
    rows_q3 = cursor.fetchall()
    headers_q3 = [
        "ID",
        "Company Name",
        "Tier",
        "Region",
        "Plan",
        "Cycle",
        "Monthly Rate",
        "Payment Status",
    ]
    print(format_table(headers_q3, rows_q3))
    print(f"Returned {len(rows_q3)} records.\n")

    # Query 4: Multi-step Support Query
    # Total monthly revenue of Enterprise tier vs total company monthly revenue & percentage share
    print("-" * 80)
    print("QUERY 4 (MULTI-STEP CALCULATION): Enterprise Tier Revenue Contribution")
    print("-" * 80)
    q4 = """
    WITH tier_totals AS (
        SELECT
            c.tier,
            SUM(s.monthly_rate) AS tier_monthly_revenue
        FROM customers c
        JOIN subscriptions s ON c.customer_id = s.customer_id
        GROUP BY c.tier
    ),
    overall_total AS (
        SELECT SUM(monthly_rate) AS total_company_revenue
        FROM subscriptions
    )
    SELECT
        t.tier,
        PRINTF('$%.2f', t.tier_monthly_revenue) AS enterprise_revenue,
        PRINTF('$%.2f', o.total_company_revenue) AS total_revenue,
        PRINTF(
            '%.2f%%', (t.tier_monthly_revenue * 100.0) / o.total_company_revenue
        ) AS revenue_share_pct
    FROM tier_totals t, overall_total o
    WHERE t.tier = 'Enterprise';
    """
    cursor.execute(q4)
    rows_q4 = cursor.fetchall()
    headers_q4 = ["Tier", "Enterprise MRR", "Company Total MRR", "Revenue Share %"]
    print(format_table(headers_q4, rows_q4))
    print(f"Returned {len(rows_q4)} record.\n")

    # Bonus Operational Query: Incidents & Downtime Analysis by Customer
    print("-" * 80)
    print("QUERY 5 (OPERATIONAL JOIN & AGGREGATION): Top Incidents & Downtime by Customer")
    print("-" * 80)
    q5 = """
    SELECT
        c.customer_id,
        c.company_name,
        c.tier,
        COUNT(t.ticket_id) AS total_tickets,
        SUM(t.downtime_minutes) AS total_downtime_mins,
        SUM(t.sla_breached) AS sla_breaches,
        MAX(t.reported_at) AS latest_incident
    FROM customers c
    JOIN incident_tickets t ON c.customer_id = t.customer_id
    GROUP BY c.customer_id, c.company_name, c.tier
    ORDER BY total_downtime_mins DESC
    LIMIT 5;
    """
    cursor.execute(q5)
    rows_q5 = cursor.fetchall()
    headers_q5 = [
        "ID",
        "Company Name",
        "Tier",
        "Tickets",
        "Total Downtime (m)",
        "SLA Breaches",
        "Latest Incident",
    ]
    print(format_table(headers_q5, rows_q5))
    print(f"Returned {len(rows_q5)} records.\n")


def main():
    try:
        conn = init_database()
        validate_records(conn)
        run_sample_queries(conn)
        conn.close()
        print("=" * 80)
        print("DATABASE INITIALIZATION & VERIFICATION COMPLETED SUCCESSFULLY (0 ERRORS)")
        print("=" * 80)
    except Exception as e:
        print(f"\nERROR during database execution: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
