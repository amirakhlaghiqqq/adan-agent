# CloudScale RAG evaluation question set

Draft question bank, created 2026-10-22. Contains 36 questions: 12 easy, 12 medium, and 12 hard. Difficulty is a design judgment, not a measured result; calibrate it after running the system. This is a question bank and scoring guide, not an executed benchmark.

An additional [12 hybrid questions](hybrid_questions.md) require both policy PDFs and database retrieval, with four questions per difficulty level. Together the two files contain 48 questions. Keep document-only and hybrid scores separate so SQL and orchestration failures do not obscure RAG quality.

## Sources and evaluation conditions

- **BIL:** `data/documents/enterprise_billing_and_refund_policy.pdf`, DOC-BIL-2024-V3, February 1, 2024, **4 PDF pages**.
- **SLA:** `data/documents/sla_and_support_tier_policy.pdf`, DOC-SLA-2024-V2, January 15, 2024, **6 PDF pages**.

Page references below use the rendered PDF page numbers, not LaTeX layout comments. Evaluate against these supplied policy versions; a future review date does not prove that a newer policy exists.

Give the system only the question and access to the two PDFs. Keep this answer key outside its retrieval corpus and prompts. Hypothetical facts explicitly stated in a question may be used. No database queries, external legal knowledge, or external tax rates are needed. These cases evaluate the document RAG capability; SQL and tool orchestration need separate cases.

For every answer, ask the system to cite the document and page or section supporting its material claims. Equivalent wording and equivalent source passages are acceptable. A citation alone does not prove that a claim is supported.

Each **Expected** entry is a checklist of required facts, not an exact-match answer. **Avoid** identifies a particularly important error; it is not an exhaustive list of errors. For missing-information cases, the listed source explains the limit or adjacent policy; it is not proof of the missing fact. Absence was checked against both PDFs.

## Easy: direct retrieval

### E01 — Annual billing discount

**Question:** What upfront discount does CloudScale offer for annual Enterprise subscriptions, and how long is the prepaid term?

**Expected:** A 15% discount relative to standard monthly rates; a continuous 12-month term prepaid in advance.

**Evidence:** BIL p. 1, §1.2.

**Tests:** Factual correctness; completeness of a two-part answer.

### E02 — Approved refund timing

**Question:** Once an Enterprise refund is approved, how long does CloudScale take to return it, and where is it sent?

**Expected:** 5–10 business days; returned to the original payment method; bank processing may cause additional settlement delay.

**Evidence:** BIL p. 2, §3.5.

**Tests:** Correct units; qualifications; completeness.

### E03 — Monthly refund rule

**Question:** If I cancel my Enterprise monthly subscription after the billing cycle starts, do I get a partial refund, and when does access end?

**Expected:** No partial or prorated refund; cancellation stops future renewals; access continues through the current 30-day period.

**Evidence:** BIL p. 2, §3.3.

**Tests:** Direct policy retrieval; completeness.

### E04 — Billing contacts

**Question:** Which email addresses should an Enterprise customer use for a billing dispute and for a tax exemption request?

**Expected:** Billing disputes: `billing@cloudscale.io`; tax exemption: `tax@cloudscale.io`.

**Evidence:** BIL p. 4, §§5.1, 5.3–5.4.

**Tests:** Exact entity retrieval; correct assignment of contacts.

### E05 — Read-only suspension

**Question:** On which overdue day does an Enterprise account enter read-only suspension, and what can the customer still do?

**Expected:** Day 14 if payment is unsettled; customers can view, query, and export stored data. Writes, new computing workloads, and API data writes are blocked.

**Evidence:** BIL p. 3, §4; p. 4, Table 1 is equivalent evidence.

**Tests:** Numeric fact retrieval; operational consequences.

### E06 — Payment methods

**Question:** Which credit card brands does CloudScale accept, and when are card payments charged?

**Expected:** Visa, MasterCard, and American Express/Amex; automatically on the invoice issuance date.

**Evidence:** BIL p. 1, §2.1.

**Tests:** List completeness; date-event precision.

### E07 — Uptime commitments

**Question:** What are the monthly uptime commitments for Professional and Enterprise customers?

**Expected:** Professional: 99.90%; Enterprise: 99.99%.

**Evidence:** SLA p. 2, §3.1, Table 1.

**Tests:** Table retrieval; avoiding swapped values.

### E08 — Enterprise critical response

**Question:** What is the guaranteed initial response time for an Enterprise Severity 1 incident, and when is that coverage available?

**Expected:** At most 30 minutes; 24/7 dedicated coverage.

**Evidence:** SLA p. 4, §5.2, Table 3.

**Avoid:** Describing this as a guaranteed resolution time.

**Tests:** Table retrieval; meaning of the measured interval.

### E09 — Claim deadline

**Question:** How long does a customer have to file an SLA service-credit claim, and when does that filing period begin?

**Expected:** Within 30 calendar days following the end of the calendar month in which downtime occurred; late claims are permanently forfeited.

**Evidence:** SLA p. 3, §4.3.

**Avoid:** Starting the deadline at the incident timestamp.

**Tests:** Temporal anchoring; calendar versus business days.

### E10 — Maintenance notice

**Question:** How much advance notice is required for scheduled maintenance, and what is the standard maintenance window?

**Expected:** At least 48 hours' written notice; Sundays, 01:00–05:00 UTC.

**Evidence:** SLA p. 2, §3.3.

**Tests:** Time and timezone precision.

### E11 — Starter credits

**Question:** Can a Starter customer receive an SLA service credit for an outage?

**Expected:** No; Starter is expressly excluded and receives 0% service credits under all circumstances.

**Evidence:** SLA p. 2, §4.1; p. 1, §2 is also supporting evidence.

**Tests:** Explicit exclusion retrieval.

### E12 — Covered services

**Question:** What three core platform systems are covered by CloudScale's SLA?

**Expected:** Cloud Infrastructure; Managed Database Engine; CloudScale API Platform.

**Evidence:** SLA p. 1, §1.1.

**Tests:** List completeness; scope retrieval.

## Medium: synthesis and conditional application

### M01 — All Net-30 prerequisites

**Question:** Our Enterprise company has a $30,000 annual contract. Is that alone enough to receive Net-30 terms? Explain every approval requirement and the payment period.

**Expected:** No. Requires a passed corporate credit risk assessment approved by Finance; either two consecutive years of audited financial statements or three verified commercial credit trade references; and an active contract with ACV of at least $24,000 USD or 24,000 EUR. Net-30 grants 30 calendar days from invoice issuance to settle. The stated contract value satisfies only the threshold, assuming the contract is active.

**Evidence:** BIL p. 2, §2.3.

**Avoid:** Requiring both financial-documentation alternatives or promising automatic approval.

**Tests:** AND/OR conditions; completeness; qualified conclusion.

### M02 — Annual refund and non-refundable extras

**Question:** We activated an annual Enterprise subscription 10 days ago and used 40 computing hours. We are submitting a written refund request today for the subscription, custom onboarding, and data migration engineering. Which charges qualify under the policy, and how are approved refunds returned?

**Expected:** The subscription meets the stated 14-day written-request and under-50-hour conditions; custom onboarding and data migration engineering are non-refundable. Approved refunds go to the original payment method within 5–10 business days, with possible bank settlement delays.

**Evidence:** BIL p. 2, §§3.2, 3.4–3.5.

**Tests:** Multi-section synthesis; exceptions; answer completeness.

### M03 — Upgrades versus downgrades

**Question:** An Enterprise customer wants to add compute nodes today and reduce capacity later in the same billing cycle. How do the effective dates and billing treatments differ?

**Expected:** Upgrades/additions take effect immediately with an immediate prorated charge for remaining cycle days to the payment method on file. Reductions/downgrades start next cycle; no mid-term credit, cash refund, or prorated reimbursement for the active cycle.

**Evidence:** BIL p. 1, §1.4.

**Tests:** Comparison; preservation of asymmetric rules.

### M04 — Delinquency timeline

**Question:** Summarize what happens to an unpaid Enterprise account from the due date passing through permanent data deletion, including retries, warnings, access changes, fees, and the recovery opportunity.

**Expected:** Days 1–7: full-access grace period; retries on days 3 and 6. Day 8: formal overdue email. Day 14: read-only suspension, with viewing/querying/export retained. Day 30: final default notice and monthly 1.5% late fee or statutory limit. Day 45: termination and compute shutdown. Days 46–60: recovery hold; restoration requires full payment of unpaid invoices and accrued late fees. Day 61: irreversible deletion of configurations, databases, snapshots, and API keys.

**Evidence:** BIL pp. 2–3, §4; p. 4, Table 1.

**Tests:** Long-answer completeness; cross-page retrieval; sequence accuracy.

### M05 — Chargeback consequences

**Question:** An Enterprise customer starts an unjustified bank chargeback without contacting CloudScale first. What should they have done, what happens to their account, and what payments are required for reinstatement?

**Expected:** Contact Billing Support at `billing@cloudscale.io` to investigate first. Active chargeback dispute causes immediate administrative suspension. An unjustified chargeback without prior notice incurs a $25 USD administrative fee. Reinstatement requires the original invoice total, the $25 fee, and any third-party bank dispute fees incurred by CloudScale.

**Evidence:** BIL p. 4, §5.1.

**Tests:** Multi-part coverage; correct conditions for fees.

### M06 — VAT versus tax exemption

**Question:** How does tax treatment differ between an Enterprise customer with a verified EU VAT ID and a tax-exempt organization that submits its certificate only after an invoice was generated?

**Expected:** A verified EU VAT ID enables reverse-charge invoicing at 0% VAT. Tax exemption requires a valid state-issued certificate sent to `tax@cloudscale.io` before invoice generation and formal review/verification; taxes on invoices generated before that verification cannot be retrospectively credited or refunded.

**Evidence:** BIL p. 4, §§5.2–5.3.

**Tests:** Adjacent-rule separation; timing; exceptions.

### M07 — Severity 2 comparison

**Question:** For Severity 2 incidents, compare Professional and Enterprise initial response limits, coverage, and ongoing update intervals.

**Expected:** Professional: initial response within 6 business hours, updates every 6 hours. Enterprise: initial response within 2 hours with 24/7/365 coverage, updates every 2 hours. Professional standard support is Monday–Friday, 08:00–20:00 US Eastern; its 24/7 exception is Severity 1, not Severity 2.

**Evidence:** SLA p. 4, §§5.2–5.4, Table 3.

**Tests:** Table-plus-prose synthesis; tier and coverage distinctions.

### M08 — Complete credit claim

**Question:** What must an eligible customer include in an SLA credit claim, where can they submit it, and what deadline must they meet?

**Expected:** Account ID and organization name; exact outage dates, start times, and duration; impacted service endpoints; customer-side error logs or traceroute data. Submit to `billing-credits@cloudscale.io` or the billing portal ticket system within 30 calendar days after the affected month's end.

**Evidence:** SLA p. 3, §4.3.

**Tests:** List completeness; deadline and channel precision.

### M09 — Maintenance conditions

**Question:** Compare three ordinary scheduled maintenance events: (A) two hours on Sunday from 01:00 UTC with 72 hours' notice and no other maintenance that month; (B) the same event with only 24 hours' notice; and (C) an otherwise compliant event that brings cumulative monthly maintenance to five hours. What is excluded from downtime, and what counts?

**Expected:** A qualifies as excluded scheduled maintenance. B counts as downtime because it lacks 48 hours' notice. For C, maintenance beyond the four-hour monthly cap counts as downtime; do not automatically label all five hours as chargeable downtime. These are scheduled, not emergency, events.

**Evidence:** SLA p. 2, §3.3; p. 5, §6 item 7.

**Tests:** Conditional application; cap handling; retrieval across sections.

### M10 — Credit bracket comparison

**Question:** Assuming all other eligibility and filing requirements are met, what credit percentages apply to Enterprise and Professional customers at exactly 99.90% monthly uptime and at exactly 98.50%? How are those credits delivered, and can they be cashed out?

**Expected:** At 99.90%: Enterprise 10%, Professional 0%. At 98.50%: Enterprise 50%, Professional 25%. Credits apply against subsequent/future invoices, cannot be exchanged for cash, wire transfers, or chargebacks, and total monthly credits cannot exceed 100% of that month's recurring fee.

**Evidence:** SLA p. 3, §§4.2–4.4, Table 2.

**Tests:** Table interpretation; exact boundary; delivery limitations.

### M11 — Downtime definition and measurement

**Question:** What does the SLA count as downtime, how is monthly uptime calculated, and how does CloudScale monitor availability?

**Expected:** A continuous period of at least one minute in which covered services are completely inaccessible across all availability zones, or HTTP 5xx error rate exceeds 5.0% across valid customer API requests. Monthly uptime = ((scheduled monthly minutes − downtime minutes) / scheduled monthly minutes) × 100. Synthetic probes check every 60 seconds from US-East, US-West, EU-Central, AP-East, and AU-Southeast.

**Evidence:** SLA p. 2, §3.2.

**Avoid:** Replacing “exceeds 5.0%” with “at least 5.0%,” or counting an isolated client-side failure automatically.

**Tests:** Formula retrieval; threshold precision; completeness.

### M12 — Excluded outage causes

**Question:** Assuming each event's sole cause is known, which of these causes are explicitly excluded from SLA downtime and credits: an expired customer-uploaded TLS certificate, an external ISP outage, an experimental API failure, and requests rejected for exceeding contractual quotas? Explain each classification.

**Expected:** All four are excluded: client misconfiguration; third-party internet outage; beta/pre-release service; resource quota violation/rate throttling, respectively.

**Evidence:** SLA p. 5, §6 items 1, 3, 5, and 6.

**Tests:** Semantic matching; multiple exclusions; relevance.

## Hard: ambiguity, boundaries, and unsupported requests

### H01 — Conflicting annual cancellation wording

**Question:** My annual Enterprise contract renews in 10 days. Section 3.1 says cancellation requires 48 hours' notice, so can you guarantee that cancelling today will prevent annual renewal? Reconcile the relevant policy clauses.

**Expected:** No guarantee. §1.3 specifically requires written annual cancellation notice at least 30 calendar days before expiration; 10 days does not meet that deadline. §3.1 gives a general 48-hour notice statement. Identify the conflicting/general-versus-specific wording rather than silently ignoring a clause; advise confirmation with Billing for this late annual request.

**Evidence:** BIL p. 1, §1.3; p. 2, §3.1.

**Avoid:** Inventing a formal precedence rule, a guaranteed waiver, or guaranteed renewal prevention.

**Tests:** Conflicting evidence; uncertainty; resistance to a leading premise.

### H02 — Starter target versus guarantee

**Question:** The uptime table lists 99.00% for Starter. Does that give Starter customers an enforceable uptime guarantee and service credits below 99.00%? Explain the apparent inconsistency.

**Expected:** The table does list a 99.00% target, but §2 expressly says Starter has no uptime guarantees and §4.1 excludes Starter from all credits (0%). Acknowledge the target-versus-guarantee tension. Do not infer enforceable compensation rights from the table or invent an explanation for the drafting inconsistency.

**Evidence:** SLA p. 1, §2; p. 2, §§3.1 and 4.1.

**Tests:** Contradiction awareness; qualification; full evidence retrieval.

### H03 — Exact refund thresholds

**Question:** Two annual Enterprise customers submit written requests within 14 calendar days of initial activation. Customer A has used exactly 50 computing hours; Customer B has used 49.9 hours. Which meets the guarantee's usage condition? Would the same guarantee apply to a request submitted after the 14-day window?

**Expected:** A fails: 50 or more hours is non-refundable. B meets the under-50 condition and, given the stated timely written request, the guarantee's stated requirements. A request after the window is non-refundable even with low usage; access continues through the paid annual term.

**Evidence:** BIL p. 2, §3.2.

**Tests:** Strict versus inclusive inequalities; multiple necessary conditions.

### H04 — Distinguishing refunds from outage credits

**Question:** An Enterprise customer is six months into an annual term and experiences a qualifying covered outage. They file a fully documented credit claim on time and ask for a cash refund for the unused annual term instead of a future-invoice credit. What remedy do the documents support? No monthly uptime figure is provided.

**Expected:** The annual 14-day refund window has passed; cancellation is non-refundable and access continues until the paid term ends. SLA compensation is a future-invoice service credit, not cash; it is the sole financial remedy for downtime and is capped at 100% of the monthly recurring fee. The credit percentage/amount cannot be determined without monthly uptime and, for an amount, the applicable monthly fee.

**Evidence:** BIL p. 2, §3.2; SLA p. 3, §§4.2–4.4.

**Tests:** Cross-document synthesis; remedy distinction; partial answer plus uncertainty.

### H05 — Payment suspension is not a covered outage

**Question:** An Enterprise account is 14 days overdue and its API write calls are blocked under the billing suspension policy. The customer describes this as a Severity 1 outage and asks for an SLA service credit. What do the two policies say about access and credit eligibility?

**Expected:** Day-14 read-only suspension blocks writes and new workloads while retaining viewing, querying, and export. SLA excludes outages caused by suspension for overdue unpaid invoices; the described suspension does not qualify for credits. A customer's severity label does not override the exclusion.

**Evidence:** BIL p. 3, §4 (or p. 4, Table 1); SLA p. 5, §6 item 8.

**Tests:** Cross-document reasoning; cause versus symptom; leading labels.

### H06 — Unsupported exact commercial rates

**Question:** What is CloudScale's exact price per extra computing hour and per extra GB of network egress for Enterprise customers?

**Expected:** The supplied documents do not state either numerical rate. Explain that excess usage is metered hourly and billed at month-end at contracted standard rates; the relevant contract/rate schedule is needed for exact prices.

**Evidence:** BIL p. 1, §1.5 supports only the billing mechanism, not numeric rates.

**Avoid:** Inventing a price, importing another cloud provider's prices, or confusing metering frequency with a unit price.

**Tests:** Abstention; relevant partial answer; hallucination resistance.

### H07 — Missing first-response evidence

**Question:** An Enterprise Severity 1 ticket was opened at 08:00 UTC and resolved at 09:15 UTC. Based only on those two timestamps and the policies, did CloudScale breach its initial response SLA?

**Expected:** Cannot determine. Initial response must occur within 30 minutes (by 08:30 UTC), but is measured to the first substantive qualified-engineer response, not resolution. That response timestamp is missing; a 75-minute resolution does not establish a response breach.

**Evidence:** SLA p. 4, §5.2, definition and Table 3.

**Tests:** Insufficient evidence; metric distinction; bounded inference.

### H08 — Refund eligibility with missing usage

**Question:** We activated an annual Enterprise subscription 10 days ago and sent a written refund request today. Can you confirm we qualify for the money-back guarantee? We have not supplied compute usage.

**Expected:** Timing and written-request conditions are met, but eligibility cannot be confirmed until total usage during the initial 14-day window is established as under 50 computing hours. Request/check usage; 50 or more disqualifies. Do not turn this into a definitive rejection either.

**Evidence:** BIL p. 2, §3.2.

**Tests:** Calibrated uncertainty; missing necessary condition; useful clarification.

### H09 — Missing retention policy

**Question:** For an Enterprise customer that voluntarily cancels while fully paid, how many days does CloudScale retain its production databases and backups after the paid term ends?

**Expected:** Not specified in the supplied documents. Annual/monthly cancellation rules describe access through the paid term, but the 15-day recovery hold and day-61 deletion belong to overdue-account termination. Those delinquency deadlines cannot establish voluntary-cancellation retention.

**Evidence:** BIL p. 2, §§3.2–3.3; pp. 3–4, §4 and Table 1 show the distinct delinquency scenario.

**Tests:** Abstention despite similar retrieved text; scope separation.

### H10 — Scope transfer across tiers

**Question:** A Starter customer wants the 15% annual discount, Enterprise Net-30 terms, and an SLA service credit after a major outage. Which of these entitlements can you establish from the supplied policies?

**Expected:** The billing document governs Enterprise accounts, so it does not establish Starter entitlement to that discount or Enterprise Net-30 terms; this is insufficient evidence, not proof that no separate Starter commercial terms could exist. The SLA expressly rules out Starter service credits under all circumstances.

**Evidence:** BIL p. 1, §§1.1–1.2; p. 2, §2.3; SLA p. 2, §4.1 (and p. 1, §2).

**Tests:** Cross-document scope; known exclusion versus unsupported entitlement.

### H11 — Credit bracket boundary stress test

**Question:** Assuming all other credit requirements are met, compare Enterprise and Professional service-credit percentages at exactly 99.99%, 99.90%, 99.00%, 98.00%, and 95.00% monthly uptime, and at 94.99%.

**Expected:**

| Monthly uptime | Enterprise | Professional |
|---|---:|---:|
| 99.99% | 0% | 0% |
| 99.90% | 10% | 0% |
| 99.00% | 25% | 10% |
| 98.00% | 50% | 25% |
| 95.00% | 50% | 50% |
| 94.99% | 100% | 100% |

The first row follows from meeting both tier commitments; the remaining rows follow the inclusive lower and exclusive upper bracket bounds. These percentages describe credits against the monthly fee, not percentages of downtime.

**Evidence:** SLA p. 2, §§3.1 and 4.1; p. 3, §4.2, Table 2.

**Tests:** Table boundary reasoning; many-cell completeness; supported inference.

### H12 — Late claim with a valid outage

**Question:** A Professional customer has an otherwise eligible covered outage month with 98.50% uptime. They submit a fully documented claim 31 calendar days after that month's end and argue that the credit table guarantees a 25% cash refund. Is their request valid? Explain both the deadline and remedy issues.

**Expected:** The table's nominal Professional bracket at 98.50% is a 25% monthly-fee service credit, subject to eligibility and filing requirements. The claim is beyond 30 calendar days and is permanently forfeited. Even a timely accepted claim would produce a future-invoice credit, not a cash refund.

**Evidence:** SLA p. 3, §§4.2–4.4.

**Tests:** Multiple clauses; exceptions overriding a nominal bracket; false-premise correction.

## Scoring guide

Use separate metrics so one good-looking number does not hide a failure. These are project-specific operational definitions, not claims of compatibility with a particular evaluation library.

| Dimension | What to assess | Suggested score |
|---|---|---|
| Correctness | Does the conclusion and each substantive fact agree with the reference evidence and stated hypothetical facts? | 0 = wrong conclusion/material factual error; 1 = partly correct or materially imprecise; 2 = correct. |
| Completeness | Does the answer cover the required facts and qualifications in the Expected checklist? | Required facts covered / total required facts. Split compound checklist statements into atomic facts before automated scoring. |
| Faithfulness | Are the answer's material factual claims supported by the actual retrieved context or by the question's explicit facts? | Supported material claims / total material claims. Mark no-claim answers N/A and assess abstention separately. |
| Citation precision | Do the cited document and page/section actually support their attached claims? | Supported claim–citation pairs / all claim–citation pairs. No citations = N/A here; citation coverage captures the omission. |
| Citation coverage | How many externally verifiable answer claims have a valid supporting citation? | Claims with valid citations / externally verifiable answer claims. Treat purely hypothetical input facts separately. |
| Relevance | Does the answer address the question without unrelated policy exposition? | 0 = mostly irrelevant; 1 = useful but distracting; 2 = focused. |
| Uncertainty handling | Does it answer supported parts, identify absent facts/conflicts, and avoid unsupported certainty or unnecessary refusal? | 0 = fabricated/certain despite missing evidence, or unjustified refusal; 1 = vague/partial; 2 = appropriately calibrated. |

Correctness and faithfulness are different: an answer can match the reference by guessing while lacking support in its retrieved context. Conversely, it can faithfully repeat an incomplete retrieved passage yet miss a relevant exception elsewhere. Log the actual retrieved chunks to distinguish these failures.

For retrieval evaluation, split each case's Evidence into evidence requirements. An AND requirement needs all independent facts (for example, H01 needs both cancellation clauses). Equivalent prose/table passages are OR alternatives (for example, E05 can use §4 or Table 1). Measure:

- **Evidence recall@k:** fraction of required evidence units supported by the top-k chunks.
- **All-evidence success@k:** whether all required evidence units are available together.
- **Context precision@k:** fraction of retrieved chunks useful to answering the question, judged by content rather than page labels alone.

Do not equate retrieving a page with retrieving its relevant rule. A nearby heading or footer is not sufficient evidence. For H06 and H09, evaluate retrieval of relevant limiting/adjacent policies and honest abstention; do not invent a gold passage that contains the missing answer.

Report results per difficulty and as separate slices: direct retrieval, synthesis, cross-document (H04/H05/H10), threshold reasoning (M10/H03/H11), ambiguity (H01/H02), and missing-information handling (H06–H09). Slices overlap. H07/H08 are partially answerable; a useful qualified answer is better than a blanket refusal. Include false refusal rate on answerable questions to detect a system that avoids hallucinations by declining everything.

Keep E01–H12 identifiers stable when revising wording. Several questions deliberately revisit the same rules at different difficulty levels; keep those related items in the same development/test partition if creating a held-out split. This small, document-specific bank is suitable for initial diagnosis and regression checks, not a statistically conclusive measure of general RAG quality. No model runs or scores have been produced yet.
