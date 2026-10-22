-- ============================================================================
-- CloudScale Inc. B2B SaaS Platform Seed Data
-- Dialect: SQLite 3
-- Description: Realistic seed dataset covering Enterprise, Professional,
--              and Starter customers, subscriptions, and incident tickets.
-- ============================================================================

-- ============================================================================
-- Seed Data: customers (30 tenants across 4 global regions & 3 tiers)
-- ============================================================================
INSERT INTO customers (customer_id, company_name, tier, region, contact_email, joined_date, status) VALUES
(1, 'Apex Global Technologies', 'Enterprise', 'North America', 'billing@apextech.com', '2021-03-15', 'active'),
(2, 'BioGenix Diagnostics', 'Enterprise', 'Europe', 'ops@biogenix.eu', '2021-06-20', 'active'),
(3, 'Nexus Logistics Hub', 'Enterprise', 'Asia Pacific', 'finance@nexuslogistics.com', '2021-09-10', 'active'),
(4, 'Aegis Financial Systems', 'Enterprise', 'North America', 'admin@aegisfin.com', '2022-01-08', 'active'),
(5, 'Vanguard Media Group', 'Enterprise', 'Europe', 'tech@vanguardmedia.co.uk', '2022-02-14', 'active'),
(6, 'Solaria Clean Energy', 'Enterprise', 'Latin America', 'cloud@solariaenergy.br', '2022-04-19', 'active'),
(7, 'Zenith Cloud Robotics', 'Enterprise', 'Asia Pacific', 'infra@zenithrobotics.jp', '2022-08-30', 'active'),
(8, 'Meridian Health Systems', 'Enterprise', 'North America', 'it-dept@meridianhealth.org', '2022-11-12', 'active'),
(9, 'Aura Security Labs', 'Enterprise', 'Europe', 'security@aurasec.io', '2023-01-25', 'suspended'),
(10, 'Titan Heavy Industries', 'Enterprise', 'North America', 'enterprise@titanindustries.com', '2021-11-05', 'churned'),
(11, 'Hyperion Data Analytics', 'Professional', 'North America', 'accounts@hyperiondata.io', '2022-05-18', 'active'),
(12, 'Nordic Stream Software', 'Professional', 'Europe', 'dev@nordicstream.se', '2022-07-22', 'active'),
(13, 'Pacific Crest AI', 'Professional', 'Asia Pacific', 'contact@pacificcrest.ai', '2022-09-15', 'active'),
(14, 'Andes Digital Works', 'Professional', 'Latin America', 'info@andesdigital.cl', '2022-10-01', 'active'),
(15, 'Beacon Retail Solutions', 'Professional', 'North America', 'it@beaconretail.com', '2023-02-10', 'active'),
(16, 'Crestline Insurance Tech', 'Professional', 'North America', 'ops@crestlineins.com', '2023-03-14', 'active'),
(17, 'Helios Solar Analytics', 'Professional', 'Europe', 'billing@heliossolar.de', '2023-05-02', 'active'),
(18, 'Quantum Leap EdTech', 'Professional', 'Asia Pacific', 'admin@quantumleaped.in', '2023-06-18', 'active'),
(19, 'Rio Grande Commerce', 'Professional', 'Latin America', 'finance@riograndecomm.mx', '2023-08-20', 'suspended'),
(20, 'Strata Legal Services', 'Professional', 'Europe', 'tech@stratalegal.fr', '2022-12-04', 'churned'),
(21, 'Nova Craft Studios', 'Starter', 'North America', 'hello@novacraft.io', '2023-01-11', 'active'),
(22, 'Pulse Fitness Systems', 'Starter', 'Europe', 'support@pulsefitness.co', '2023-02-28', 'active'),
(23, 'Sakura Creative Labs', 'Starter', 'Asia Pacific', 'team@sakuracreative.jp', '2023-04-12', 'active'),
(24, 'Pampa AgTech', 'Starter', 'Latin America', 'contact@pampaag.ar', '2023-05-19', 'active'),
(25, 'Kite Mobility', 'Starter', 'North America', 'founders@kitemobility.com', '2023-07-07', 'active'),
(26, 'Urban Mesh Wireless', 'Starter', 'North America', 'admin@urbanmesh.net', '2023-08-15', 'active'),
(27, 'BlueWave Audio', 'Starter', 'Europe', 'info@bluewaveaudio.nl', '2023-09-21', 'active'),
(28, 'Koru Green Living', 'Starter', 'Asia Pacific', 'hello@koruliving.nz', '2023-10-30', 'active'),
(29, 'Atlas Micro Brew', 'Starter', 'North America', 'brew@atlasmicro.beer', '2023-11-14', 'suspended'),
(30, 'PixelForge Games', 'Starter', 'Europe', 'support@pixelforge.es', '2023-03-05', 'churned');

-- ============================================================================
-- Seed Data: subscriptions (30 subscriptions with varied rates, cycles & statuses)
-- ============================================================================
INSERT INTO subscriptions (subscription_id, customer_id, plan_name, billing_cycle, monthly_rate, start_date, renewal_date, payment_status) VALUES
(1, 1, 'Enterprise Platform Suite', 'annual', 4800.00, '2023-03-15', '2024-03-15', 'paid'),
(2, 2, 'Enterprise Compliance Cloud', 'annual', 3600.00, '2023-06-20', '2024-06-20', 'paid'),
(3, 3, 'Enterprise Global Logistics', 'monthly', 4200.00, '2023-09-10', '2024-10-10', 'paid'),
(4, 4, 'Enterprise Financial Cloud', 'annual', 4800.00, '2023-01-08', '2024-01-08', 'paid'),
(5, 5, 'Enterprise Media Stream', 'annual', 2400.00, '2023-02-14', '2024-02-14', 'paid'),
(6, 6, 'Enterprise CleanTech Core', 'monthly', 1800.00, '2023-04-19', '2024-05-19', 'paid'),
(7, 7, 'Enterprise Robotics Orchestrator', 'annual', 3200.00, '2023-08-30', '2024-08-30', 'paid'),
(8, 8, 'Enterprise HIPAA Suite', 'annual', 3600.00, '2023-11-12', '2024-11-12', 'pending'),
(9, 9, 'Enterprise ThreatShield', 'monthly', 1200.00, '2023-01-25', '2024-02-25', 'overdue'),
(10, 10, 'Enterprise Core ERP', 'annual', 2400.00, '2022-11-05', '2023-11-05', 'overdue'),
(11, 11, 'Professional Data Analytics', 'annual', 499.00, '2023-05-18', '2024-05-18', 'paid'),
(12, 12, 'Professional Dev Pipeline', 'monthly', 399.00, '2023-07-22', '2024-08-22', 'paid'),
(13, 13, 'Professional AI Engine', 'annual', 449.00, '2023-09-15', '2024-09-15', 'paid'),
(14, 14, 'Professional Digital Ops', 'monthly', 299.00, '2023-10-01', '2024-11-01', 'paid'),
(15, 15, 'Professional OmniCommerce', 'annual', 399.00, '2023-02-10', '2024-02-10', 'paid'),
(16, 16, 'Professional InsurTech Suite', 'monthly', 349.00, '2023-03-14', '2024-04-14', 'pending'),
(17, 17, 'Professional Green Analytics', 'annual', 499.00, '2023-05-02', '2024-05-02', 'paid'),
(18, 18, 'Professional Learning Hub', 'monthly', 299.00, '2023-06-18', '2024-07-18', 'paid'),
(19, 19, 'Professional Merchant Portal', 'monthly', 349.00, '2023-08-20', '2024-09-20', 'overdue'),
(20, 20, 'Professional Legal Cloud', 'annual', 299.00, '2022-12-04', '2023-12-04', 'overdue'),
(21, 21, 'Starter Growth', 'monthly', 49.00, '2023-01-11', '2024-02-11', 'paid'),
(22, 22, 'Starter Growth', 'annual', 49.00, '2023-02-28', '2024-02-28', 'paid'),
(23, 23, 'Starter Standard', 'monthly', 49.00, '2023-04-12', '2024-05-12', 'paid'),
(24, 24, 'Starter Growth', 'annual', 49.00, '2023-05-19', '2024-05-19', 'paid'),
(25, 25, 'Starter Standard', 'monthly', 49.00, '2023-07-07', '2024-08-07', 'paid'),
(26, 26, 'Starter Standard', 'monthly', 49.00, '2023-08-15', '2024-09-15', 'pending'),
(27, 27, 'Starter Growth', 'annual', 49.00, '2023-09-21', '2024-09-21', 'paid'),
(28, 28, 'Starter Standard', 'monthly', 49.00, '2023-10-30', '2024-11-30', 'pending'),
(29, 29, 'Starter Standard', 'monthly', 49.00, '2023-11-14', '2024-12-14', 'overdue'),
(30, 30, 'Starter Standard', 'annual', 49.00, '2023-03-05', '2024-03-05', 'overdue');

-- ============================================================================
-- Seed Data: incident_tickets (20 incidents across severities, downtime & SLA)
-- ============================================================================
INSERT INTO incident_tickets (ticket_id, customer_id, severity, downtime_minutes, reported_at, resolved_at, status, sla_breached) VALUES
(1, 1, 'Severity 1', 75, '2024-01-14T08:15:00Z', '2024-01-14T09:30:00Z', 'resolved', 1),
(2, 2, 'Severity 2', 25, '2024-01-20T11:00:00Z', '2024-01-20T11:25:00Z', 'resolved', 0),
(3, 3, 'Severity 1', 140, '2024-02-05T03:30:00Z', '2024-02-05T05:50:00Z', 'closed', 1),
(4, 4, 'Severity 3', 0, '2024-02-12T14:10:00Z', '2024-02-12T15:00:00Z', 'closed', 0),
(5, 5, 'Severity 2', 40, '2024-02-18T10:05:00Z', '2024-02-18T10:45:00Z', 'resolved', 0),
(6, 6, 'Severity 1', 90, '2024-02-27T16:20:00Z', '2024-02-27T17:50:00Z', 'closed', 1),
(7, 7, 'Severity 2', 20, '2024-03-02T09:00:00Z', '2024-03-02T09:20:00Z', 'resolved', 0),
(8, 8, 'Severity 1', 110, '2024-03-11T13:45:00Z', '2024-03-11T15:35:00Z', 'resolved', 1),
(9, 9, 'Severity 3', 0, '2024-03-15T08:20:00Z', '2024-03-15T09:10:00Z', 'closed', 0),
(10, 10, 'Severity 2', 50, '2024-03-19T17:15:00Z', '2024-03-19T18:05:00Z', 'closed', 0),
(11, 11, 'Severity 2', 30, '2024-03-22T12:00:00Z', '2024-03-22T12:30:00Z', 'resolved', 0),
(12, 12, 'Severity 3', 0, '2024-03-25T15:30:00Z', '2024-03-25T16:00:00Z', 'closed', 0),
(13, 13, 'Severity 1', 65, '2024-03-28T07:10:00Z', '2024-03-28T08:15:00Z', 'resolved', 1),
(14, 14, 'Severity 2', 45, '2024-04-02T10:15:00Z', NULL, 'in_progress', 0),
(15, 15, 'Severity 3', 0, '2024-04-05T11:40:00Z', '2024-04-05T12:20:00Z', 'closed', 0),
(16, 16, 'Severity 2', 15, '2024-04-08T14:50:00Z', '2024-04-08T15:05:00Z', 'resolved', 0),
(17, 17, 'Severity 3', 0, '2024-04-12T09:25:00Z', '2024-04-12T10:00:00Z', 'closed', 0),
(18, 18, 'Severity 1', 125, '2024-04-15T06:00:00Z', '2024-04-15T08:05:00Z', 'closed', 1),
(19, 21, 'Severity 3', 0, '2024-04-18T13:10:00Z', '2024-04-18T13:45:00Z', 'closed', 0),
(20, 22, 'Severity 2', 35, '2024-04-20T16:40:00Z', '2024-04-20T17:15:00Z', 'resolved', 0);
