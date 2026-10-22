# Hybrid evaluation: both policy PDFs and SQLite

Twelve additional questions: four easy, four medium, and four hard. These supplement the 36 document-only questions in [questions.md](questions.md), bringing the bank to 48 questions. Difficulty is provisional until calibrated through actual runs.

Every question requires facts from **all three sources**:

- **DB:** `data/database/app.db` — customer, subscription, and incident records.
- **BIL:** `data/documents/enterprise_billing_and_refund_policy.pdf`, DOC-BIL-2024-V3, 4 pages.
- **SLA:** `data/documents/sla_and_support_tier_policy.pdf`, DOC-SLA-2024-V2, 6 pages.

These cases test SQL retrieval, document retrieval, synthesis, uncertainty, and, where needed, calculation. They are not pure RAG cases. The expected answers below were checked against the supplied database and policy text; no assistant benchmark runs have been performed.

## Conditions to include with every question

The evaluator must supply these conditions to the answering system, not hide them in the answer key:

1. Treat the database as a fixed supplied snapshot. Its account/payment statuses are snapshot labels, not a historical status ledger. Do not infer a past account state from those labels. Use the stated policy versions for the exercise; do not invent later revisions.
2. For cases calculating monthly credits, assume all recorded downtime in the specified month is qualifying, non-overlapping downtime, that the incident list is complete for that month, and that subscriptions remained covered throughout that month. Assume other credit prerequisites and timely filing are satisfied unless the question explicitly asks about them or provides different facts. These are exercise assumptions, not facts recorded in the database.
3. For credit amounts, treat `monthly_rate` as the applicable final monthly recurring fee, already reflecting any contractual discount. Do not apply the 15% annual discount again. The database has no currency column: report amounts as **currency units**, unless the question supplies a currency. Ignore taxes for credit calculations.
4. Use actual calendar-month lengths in UTC: January and March 2024 have 44,640 minutes; February 2024 has 41,760 minutes. Do not use the SLA's illustrative 30-day allowance for every month. Compare unrounded uptime against bracket thresholds; round displayed uptime to six decimal places and money to two decimal places.
5. For annual refund-window questions, use `subscriptions.start_date` as initial activation for the exercise. Do not substitute customer join dates or renewal dates. The database does not prove new activation at renewal or record refund requests, compute usage, claim filings, or invoice due dates.
6. Cite both PDFs by document and page/section, and expose the SQL and its raw result. Use an actual calculator tool for arithmetic when exercising the full system. Equivalent read-only SQL and equivalent supporting passages are acceptable.

Feed only these conditions and the selected **Question** to the evaluated system. Keep reference SQL, expected results, and scoring notes out of its prompts and retrieval corpus.

## Easy: customer-specific rule lookup

### X-E01 — Nexus: cancellation and critical support

**Question:** Look up Nexus Logistics Hub's tier, billing cycle, payment status, and recorded February 2024 incident severity. If it cancels during an already-started billing cycle, does its plan allow a prorated refund? For the recorded severity, what initial technical response time and coverage does its tier receive?

**Expected DB facts:** Enterprise; monthly; paid; ticket 3, Severity 1, February 5, 2024.

**Expected answer:** No prorated refund once the monthly cycle starts; access remains through the current 30-day period and cancellation stops future renewal charges. Enterprise Severity 1 initial response is at most 30 minutes, with 24/7 dedicated coverage. This is not a guaranteed resolution time.

**Evidence:** DB Q1 with customer `Nexus Logistics Hub`, month `2024-02`; BIL p. 2, §3.3; SLA p. 4, §5.2, Table 3.

**All-three dependency:** DB selects the plan and incident; BIL determines cancellation treatment; SLA determines response commitment.

### X-E02 — Zenith: renewal notice and incident updates

**Question:** For Zenith Cloud Robotics, retrieve its billing cycle, next recorded renewal date, and March 2024 incident severity. What notice does the plan-specific renewal clause require to stop that renewal, and how often should its tier receive updates during an incident of the recorded severity?

**Expected DB facts:** Enterprise; annual; renewal August 30, 2024; ticket 7, Severity 2.

**Expected answer:** Annual written cancellation notice at least 30 calendar days before expiration under §1.3. Enterprise Severity 2 updates every two hours. If discussing §3.1's general 48-hour language, acknowledge it instead of replacing the plan-specific annual clause with it.

**Evidence:** DB Q1, `Zenith Cloud Robotics`, `2024-03`; BIL p. 1, §1.3 (p. 2, §3.1 for the general wording); SLA p. 4, §5.3.

**All-three dependency:** DB identifies annual renewal and severity; the two PDFs supply distinct notice and support rules.

### X-E03 — Aura: suspension access and credit exclusion

**Question:** Retrieve Aura Security Labs' tier, account status, billing cycle, and payment status. For this hypothetical, Finance confirms that this account is exactly 14 days overdue and its loss of write access is solely the billing-policy suspension. What access should remain, and does this suspension qualify for an SLA service credit?

**Expected DB facts:** Enterprise; suspended; monthly; overdue.

**Expected answer:** At day 14, read-only suspension blocks writes, new workloads, and API data writes; viewing, querying, and exporting remain available. No service credit for outages caused by suspension due to unpaid overdue invoices. The exact overdue age and cause are supplied by the question, not inferred from the DB.

**Evidence:** DB Q1, `Aura Security Labs`, `2024-03`; BIL p. 3, §4 or p. 4, Table 1; SLA p. 5, §6 item 8.

**All-three dependency:** DB establishes the actual account attributes; BIL defines suspension consequences; SLA supplies the exclusion.

### X-E04 — Vanguard: downgrade and support channels

**Question:** Retrieve Vanguard Media Group's tier, billing cycle, and February 2024 incident severity. If it requests a capacity downgrade during its active term, when does that take effect and is there a mid-term credit? For the recorded incident severity, what is the tier's initial response commitment and which support channels are available?

**Expected DB facts:** Enterprise; annual; ticket 5, Severity 2.

**Expected answer:** Downgrade takes effect next billing cycle; no mid-term credit, cash refund, or prorated reimbursement for the reduction. Enterprise Severity 2 initial response within two hours, 24/7/365. Enterprise channels include dedicated telephone hotline, Slack/Teams Connect, priority portal, and dedicated TAM with Tier-3 SRE escalation.

**Evidence:** DB Q1, `Vanguard Media Group`, `2024-02`; BIL p. 1, §1.4; SLA p. 4, §§5.2 and 5.4.

**All-three dependency:** Customer and severity selection comes from DB; downgrade and support rules come from separate PDFs.

## Medium: calculation and remedy synthesis

### X-M01 — Nexus: outage credit versus cash refund

**Question:** For Nexus Logistics Hub, calculate February 2024 monthly uptime, the applicable credit percentage, and the credit amount from recorded downtime. If it asks on March 10, 2024 for that outage compensation in cash and a prorated refund for cancelling its already-started monthly cycle, which requests do the two policies support?

**Expected DB facts:** Enterprise; monthly; rate 4,200; start September 10, 2023; ticket 3; 140 downtime minutes.

**Expected calculation:** `(41760 - 140) / 41760 * 100 = 99.664751%`; Enterprise bracket 25%; `4200 * 0.25 = 1050.00` currency units.

**Expected answer:** A 25% future-invoice credit, subject to the stated exercise conditions. No cash conversion of credits; no prorated monthly cancellation refund; access continues through the paid monthly period.

**Evidence:** DB Q1, `Nexus Logistics Hub`, `2024-02`; BIL p. 2, §3.3; SLA p. 2, §3.2; p. 3, §§4.2–4.4.

**All-three dependency:** DB supplies downtime, fee, and cycle; SLA supplies calculation/bracket/remedy; BIL supplies monthly refund treatment.

### X-M02 — Solaria: two separate financial remedies

**Question:** For Solaria Clean Energy, calculate its February 2024 uptime and outage credit. It asks to cancel its already-started monthly cycle on March 5, 2024 and argues that receiving an SLA credit also makes the unused subscription refundable. Explain whether that follows from the documents.

**Expected DB facts:** Enterprise; monthly; rate 1,800; start April 19, 2023; ticket 6; 90 minutes.

**Expected calculation:** `(41760 - 90) / 41760 * 100 = 99.784483%`; 25%; `1800 * 0.25 = 450.00` currency units.

**Expected answer:** A 450.00 future-invoice service credit under the exercise conditions, not cash. Monthly cancellation does not create a partial refund, and a service credit does not override that rule. Services remain available through the current paid period.

**Evidence:** DB Q1, `Solaria Clean Energy`, `2024-02`; BIL p. 2, §3.3; SLA p. 2, §3.2; p. 3, §§4.2 and 4.4.

**All-three dependency:** DB supplies the specific amounts and cycle; SLA governs credit; BIL governs cancellation.

### X-M03 — Zenith: annual refund window and monthly credit

**Question:** On April 10, 2024, Zenith Cloud Robotics asks for an unused-term annual cash refund after its March incident. Retrieve its activation date and calculate its March monthly uptime and service credit. Explain whether the annual refund guarantee or an SLA credit is the supported remedy.

**Expected DB facts:** Enterprise; annual; activation August 30, 2023; rate 3,200; ticket 7; 20 minutes.

**Expected calculation:** `(44640 - 20) / 44640 * 100 = 99.955197%`; 10%; `3200 * 0.10 = 320.00` currency units.

**Expected answer:** Initial activation was well over 14 calendar days earlier; no unused-term annual cash refund under the guarantee. Annual access continues through the paid term. A 320.00 future-invoice SLA credit is supported under the exercise conditions; credits cannot be cashed out.

**Evidence:** DB Q1, `Zenith Cloud Robotics`, `2024-03`; BIL p. 2, §3.2; SLA p. 2, §3.2; p. 3, §§4.2–4.4.

**All-three dependency:** DB supplies activation, downtime, tier and fee; BIL decides refund window; SLA determines compensation.

### X-M04 — BioGenix: recorded breach flag versus policy credit

**Question:** For BioGenix Diagnostics, calculate its January 2024 uptime and service credit. Compare the result with its incident's stored `sla_breached` flag. On February 20, 2024, it also requests an annual subscription refund: use its initial activation date to assess that request. Does the stored flag by itself settle credit eligibility?

**Expected DB facts:** Enterprise; annual; activation June 20, 2023; rate 3,600; ticket 2 reported January 20, 2024; downtime 25; `sla_breached = 0`.

**Expected calculation:** `(44640 - 25) / 44640 * 100 = 99.943996%`; 10%; `3600 * 0.10 = 360.00` currency units.

**Expected answer:** Under the stated complete qualifying-downtime assumptions, monthly uptime is below Enterprise's 99.99% commitment and yields a 10% credit, despite the stored incident flag being zero. The flag does not define the policy's monthly credit calculation; its precise operational meaning is not documented. Refund request is well after 14 days from activation, so the annual guarantee does not support it. Credit is a future-invoice adjustment, not cash.

**Evidence:** DB Q1, `BioGenix Diagnostics`, `2024-01`; BIL p. 2, §3.2; SLA p. 2, §§3.1–3.2; p. 3, §§4.2 and 4.4.

**All-three dependency:** The flag comparison and dates require DB; both documents determine the two remedies. The incident falls after the SLA's January 15 effective date; the refund request falls after BIL's February 1 effective date.

## Hard: cohorts, missing evidence, and boundary conditions

### X-H01 — February compensation cohort

**Question:** Using the snapshot, find all active, paid Enterprise customers with positive recorded downtime in February 2024. For each, return its billing cycle, monthly downtime, uptime, applicable credit percentage, and credit amount; also return the total credit. On March 15, 2024, each asks for a cash refund of unused subscription time instead. Explain the refund treatment for the monthly and annual members using their recorded activation dates.

**Expected DB/result table:**

| Customer | Cycle | Activation | Downtime | Uptime | Credit | Amount (currency units) |
|---|---|---|---:|---:|---:|---:|
| Nexus Logistics Hub | monthly | 2023-09-10 | 140 | 99.664751% | 25% | 1,050.00 |
| Vanguard Media Group | annual | 2023-02-14 | 40 | 99.904215% | 10% | 240.00 |
| Solaria Clean Energy | monthly | 2023-04-19 | 90 | 99.784483% | 25% | 450.00 |

**Expected answer:** Three customers; combined credit **1,740.00 currency units** under the common-unit exercise assumption below. Nexus and Solaria have no prorated monthly refund after the cycle starts. Vanguard is beyond the initial 14-day annual window, even if a renewal has occurred; the document does not restart the initial-activation guarantee at renewal. No service credit may be converted to cash.

**Additional visible assumption:** For this question only, all three `monthly_rate` values share the same unspecified currency unit, allowing a meaningful sum. Without this assumption, the DB has insufficient currency information to justify a monetary total across customers.

**Evidence:** DB Q2; BIL p. 2, §§3.2–3.3; SLA p. 2, §3.2; p. 3, §§4.2 and 4.4.

**Avoid:** Excluding Vanguard because `sla_breached = 0`; counting Aegis's zero-downtime incident as positive downtime; using an inner assumption about currency without disclosure.

**All-three dependency:** DB determines the cohort and numeric inputs; SLA determines credits; BIL determines member-specific refund treatment.

### X-H02 — Aura: insufficient evidence for enforcement stage

**Question:** Retrieve Aura Security Labs' account status, payment status, subscription cycle, renewal date, and March incident. Based only on those records and the two policies, can you determine whether the account is at day 14, day 45, or day 61 of delinquency, whether its data has been deleted, or whether its suspension qualifies for an SLA credit? Separate known facts from conditional rules and missing evidence.

**Expected DB facts:** Enterprise; suspended; overdue; monthly; renewal February 25, 2024; ticket 9 reported March 15, Severity 3, zero recorded downtime, closed.

**Expected answer:** Cannot determine overdue age, enforcement stage, or deletion from these fields: invoice due date, enforcement history, and suspension cause are absent. Renewal date is not an invoice due date. BIL defines read-only suspension at day 14, termination at day 45, recovery hold on days 46–60, and deletion at day 61, but records do not establish which stage applies. SLA excludes suspension caused by overdue invoices; that is conditional here because the cause is not recorded. SLA also applies to active accounts in good standing, whereas this snapshot is suspended. The recorded ticket has zero downtime and provides no basis for a positive downtime credit. Do not confirm a credit or assert that all actual incidents are known beyond the stated exercise scope.

**Evidence:** DB Q1, `Aura Security Labs`, `2024-03`; BIL pp. 3–4, §4/Table 1; SLA p. 1, §1.2; p. 5, §6 item 8; p. 3, §4.2 for bracket reasoning if used.

**All-three dependency:** DB establishes limited facts and schema gaps; BIL supplies the distinct enforcement stages; SLA supplies applicability and exclusions.

### X-H03 — European account: currency and VAT uncertainty

**Question:** Among active, paid Enterprise accounts in Europe, select the one with the highest recorded monthly rate. Report its billing cycle and January 2024 downtime, then compute its nominal January SLA credit. Can the database and billing policy establish that the amount is in euros and should have 0% VAT? State the credit amount only as precisely as the evidence allows.

**Expected DB facts:** BioGenix Diagnostics; Europe; Enterprise; active; paid; annual; rate 3,600; January downtime 25 minutes. It outranks Vanguard's rate of 2,400 among the matching snapshot accounts.

**Expected calculation:** 99.943996% uptime; 10% credit; **360.00 currency units**, without invented currency or tax adjustments.

**Expected answer:** Europe alone does not establish EU registration, selected contract currency, or verified EU VAT ID. BIL makes EUR available to relevant registered clients but says selection is fixed at contract execution; verified EU VAT ID enables reverse charge at 0%. Those records are missing. Do not label the credit €360 or calculate a tax-inclusive credit from the region alone. Use the supplied BIL version to assess what can be established about billing attributes, not to assert a tax treatment actually used on a historical invoice.

**Evidence:** DB Q3; BIL pp. 1–2, §2.2 and p. 4, §5.2; SLA p. 2, §3.2; p. 3, §4.2.

**All-three dependency:** DB selects the account and numeric inputs; SLA determines credit; BIL determines which currency/tax facts remain unsupported.

### X-H04 — Zenith: late renewal notice and claim boundary

**Question:** Look up Zenith Cloud Robotics' annual renewal date and March 2024 downtime. Assess two separate hypothetical actions: (A) written cancellation notice on August 10, 2024 for the recorded renewal, and (B) a fully documented March credit claim filed on April 30, 2024 versus May 1, 2024. Calculate the nominal March credit, explain the two claim outcomes, and address the customer's claim that 48 hours' cancellation notice is sufficient for annual renewal.

**Expected DB facts:** Enterprise; annual; renewal August 30, 2024; rate 3,200; ticket 7; March downtime 20 minutes.

**Expected calculation:** 99.955197% uptime; 10%; 320.00 currency units. August 10 is 20 calendar days before August 30. April 30 is 30 calendar days after March 31; May 1 is 31 days after March 31.

**Expected answer:** The annual-specific clause requires at least 30 days' written notice, so August 10 misses that requirement. Explicitly acknowledge §3.1's general 48-hour wording without guaranteeing that it overrides the annual clause; confirm handling with Billing. April 30 meets the credit filing window under the exercise's calendar-day date convention; May 1 is late and the claim is permanently forfeited. A valid accepted claim yields a 320.00 future-invoice credit, not cash.

**Additional visible assumption:** Interpret filing on a calendar date as meeting that date's deadline, without a time-of-day cutoff; evaluate the two hypothetical claim filings independently, not as sequential submissions.

**Evidence:** DB Q1, `Zenith Cloud Robotics`, `2024-03`; BIL p. 1, §1.3 and p. 2, §3.1; SLA p. 2, §3.2; p. 3, §§4.2–4.4.

**All-three dependency:** DB supplies renewal and incident inputs; BIL supplies cancellation clauses; SLA supplies credit and filing rules.

## Reference SQL

These are evaluator reference queries, not required SQL strings. The system must generate its own read-only SQL from schema information. Compare result semantics, not exact SQL text.

### Q1 — Named customer and incident month

Bind `:company_name` to the case's customer and `:month` to its `YYYY-MM` month. A left join preserves the customer even if no incident exists in that month. Sum downtime across all returned incident rows when calculating monthly uptime; do not assume one incident per customer in the general implementation.

```sql
SELECT c.customer_id, c.company_name, c.tier, c.region,
       c.status AS account_status, s.subscription_id,
       s.billing_cycle, s.monthly_rate, s.start_date, s.renewal_date,
       s.payment_status, i.ticket_id, i.severity, i.downtime_minutes,
       i.reported_at, i.resolved_at, i.status AS incident_status,
       i.sla_breached
FROM customers AS c
JOIN subscriptions AS s ON s.customer_id = c.customer_id
LEFT JOIN incident_tickets AS i
  ON i.customer_id = c.customer_id
 AND substr(i.reported_at, 1, 7) = :month
WHERE c.company_name = :company_name
ORDER BY s.subscription_id, i.ticket_id;
```

### Q2 — February cohort with positive downtime

Aggregate incidents before joining subscriptions to avoid multiplying incident totals if a future dataset has multiple subscriptions per customer. This snapshot has one subscription per customer.

```sql
WITH monthly_incidents AS (
  SELECT customer_id, SUM(downtime_minutes) AS downtime_minutes
  FROM incident_tickets
  WHERE reported_at >= '2024-02-01T00:00:00Z'
    AND reported_at < '2024-03-01T00:00:00Z'
  GROUP BY customer_id
  HAVING SUM(downtime_minutes) > 0
)
SELECT c.customer_id, c.company_name, s.billing_cycle,
       s.start_date, s.monthly_rate, m.downtime_minutes
FROM customers AS c
JOIN subscriptions AS s ON s.customer_id = c.customer_id
JOIN monthly_incidents AS m ON m.customer_id = c.customer_id
WHERE c.tier = 'Enterprise'
  AND c.status = 'active'
  AND s.payment_status = 'paid'
ORDER BY c.customer_id;
```

### Q3 — Highest-rate matching European account and January incidents

```sql
WITH chosen AS (
  SELECT c.customer_id, c.company_name, c.tier, c.region,
         c.status AS account_status, s.billing_cycle,
         s.payment_status, s.monthly_rate
  FROM customers AS c
  JOIN subscriptions AS s ON s.customer_id = c.customer_id
  WHERE c.tier = 'Enterprise' AND c.region = 'Europe'
    AND c.status = 'active' AND s.payment_status = 'paid'
  ORDER BY s.monthly_rate DESC, c.customer_id
  LIMIT 1
)
SELECT chosen.*, i.ticket_id, i.downtime_minutes, i.reported_at
FROM chosen
LEFT JOIN incident_tickets AS i
  ON i.customer_id = chosen.customer_id
 AND i.reported_at >= '2024-01-01T00:00:00Z'
 AND i.reported_at < '2024-02-01T00:00:00Z'
ORDER BY i.ticket_id;
```

## Scoring and verification

Use the correctness, completeness, faithfulness, citation, relevance, uncertainty, and retrieval definitions in [questions.md](questions.md). Add these hybrid checks and report them separately:

- **SQL/result correctness:** Query is read-only; retrieves the correct customer/cohort, columns, incident month, and raw values. No hard-coded answers or policy rules substituted for data retrieval.
- **Three-source evidence coverage:** Correct supporting DB results plus relevant passages from both PDFs are present. If any source is missing, label the run incomplete for the all-three requirement even if some conclusions happen to be right.
- **Source attribution:** Distinguish stored facts, user-supplied hypothetical facts, retrieved rules, and calculated conclusions. SQL results are supported context for DB-derived claims; PDF citations are required for policy claims.
- **Calculation correctness:** Actual month length, complete monthly aggregation, unrounded bracket comparison, correct fee basis, and final rounding. For numerical answer checks, allow ±0.000001 percentage points for displayed uptime and ±0.01 currency units for amounts. Wrong bracket selection is a failure even if displayed rounded uptime looks close.
- **Tool execution:** For full-system evaluation, expose calculator arguments/results for required arithmetic and report missing calculator execution separately from final-answer correctness.
- **Uncertainty discipline:** Do not infer invoice due dates, historic status, currency, VAT IDs, suspension causes, or compute usage from unrelated columns. A `sla_breached` incident flag is not a replacement for monthly policy computation.

Reference data and calculations were verified using read-only SQLite queries and Python decimal/calendar arithmetic. That validates the answer key's data and arithmetic, not actual model retrieval, generated SQL, calculator-tool behavior, or end-to-end success.
