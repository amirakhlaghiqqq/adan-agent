"""Source-reviewed annotations, independent of candidate rankings and model plans.

Section mappings below were reviewed against the frozen PDFs and Docling corpus.
They are semantic judgments, not relevance inferred from heading/keyword overlap.
A sufficient set may span several chunks; alternatives are OR, chunks within a set AND.
"""
import re

# Query wording is a source-informed curated diagnostic, not a deployable planner.
TOPICS = {
    'B1.1': ('1.1', 'Which subscription tiers does the billing policy apply to?'),
    'B1.2': ('1.2', 'What annual subscription discount and prepaid duration are offered?'),
    'B1.3': ('1.3', 'What notice and process prevent monthly versus annual subscription renewal?'),
    'B1.4': ('1.4', 'When do capacity upgrades and downgrades take effect and how are they billed?'),
    'B1.5': ('1.5', 'Does the resource overage policy specify exact computing and egress prices?'),
    'B2.1': ('2.1', 'Which card brands are accepted and when are payments charged?'),
    'B2.2': ('2.2', 'How is contract billing currency selected and fixed?'),
    'B2.3': ('2.3', 'What are the mandatory approval conditions and payment period for Enterprise Net-30?'),
    'B3.1': ('3.1', 'What is the general subscription cancellation submission process and notice?'),
    'B3.2': ('3.2', 'What written request deadline and compute usage limit govern annual subscription refunds?'),
    'B3.3': ('3.3', 'Does cancelling a started monthly subscription yield a refund and when does access end?'),
    'B3.4': ('3.4', 'Are onboarding and data migration professional fees refundable?'),
    'B3.5': ('3.5', 'How are approved refunds returned and how long does processing take?'),
    'B4.grace': ('4.', 'What access and payment grace period follow an overdue invoice?'),
    'B4.full': ('4.', 'What are all overdue escalation stages, retries, warnings, fees, termination, recovery and deletion?'),
    'B4.14': ('4.', 'At fourteen days overdue, which account capabilities are blocked and which remain?'),
    'B4.stages': ('4.', 'What facts determine delinquency stage, termination and data deletion deadlines?'),
    'B5.1': ('5.1', 'What billing contact, suspension and reinstatement fees apply to an unjustified chargeback?'),
    'B5.2': ('5.2', 'What verification is required for EU VAT reverse charge?'),
    'B5.3': ('5.3', 'When must tax exemption certificates be verified and can past taxes be refunded?'),
    'B5.4': ('5.4', 'Which email addresses handle billing disputes and tax exemption?'),
    'S1.1': ('1.1', 'Which three platform systems are covered by the service availability policy?'),
    'S1.2': ('1.2', 'Which accounts in good standing are covered by the SLA?'),
    'S2.starter': ('2.', 'Does Starter include enforceable uptime, support response guarantees or credits?'),
    'S3.1': ('3.1', 'What are the monthly uptime commitments for each subscription tier?'),
    'S3.2': ('3.2', 'How are downtime and monthly uptime defined, calculated and monitored?'),
    'S3.3': ('3.3', 'What notice, time window and monthly duration limit apply to scheduled maintenance?'),
    'S4.1': ('4.1', 'Which tiers are eligible for service credits and is Starter excluded?'),
    'S4.2': ('4.2', 'What Enterprise and Professional service credit brackets apply at exact uptime boundaries?'),
    'S4.3': ('4.3', 'What claim deadline, submission channels and supporting documentation are required?'),
    'S4.4': ('4.4', 'Can service credits become cash refunds and what is the exclusive financial remedy and monthly cap?'),
    'S5.2': ('5.2', 'What initial response limits and coverage apply by incident severity and support tier?'),
    'S5.3': ('5.3', 'How frequently do Enterprise and Professional customers receive updates for Severity 1 and 2 incidents?'),
    'S5.4': ('5.4', 'Which support channels and availability apply by subscription tier?'),
    'S6.intro': ('6.', 'Which events are excluded from SLA downtime and credit eligibility?'),
    'S6.1': ('6.', 'Are customer misconfigurations and expired uploaded TLS certificates excluded from SLA coverage?'),
    'S6.3': ('6.', 'Are external internet provider outages excluded from SLA coverage?'),
    'S6.5': ('6.', 'Are experimental API failures excluded from SLA guarantees?'),
    'S6.6': ('6.', 'Are rejected requests caused by exceeding contractual quotas excluded from SLA coverage?'),
    'S6.7': ('6.', 'When is properly announced scheduled maintenance excluded from downtime?'),
    'S6.8': ('6.', 'Are outages caused by unpaid-invoice suspension eligible for service credits?'),
}


def build_annotations(cases, corpus):
    evidence_chunks = {}
    for eid, (section, _) in TOPICS.items():
        filename = ('enterprise_billing_and_refund_policy.pdf' if eid[0] == 'B'
                    else 'sla_and_support_tier_policy.pdf')
        found = [c['chunk_id'] for c in corpus if c['metadata']['source_file'] == filename
                 and re.match(r'^#+\s+' + re.escape(section) + r'(?:\s|$)', c['text'])]
        if len(found) != 1:
            raise ValueError(f'Review annotations after corpus drift: {eid}: {found}')
        evidence_chunks[eid] = found
    judgments, plans = {}, {}
    for case in cases:
        qid = case['question_id']
        groups, relevant, queries = [], set(), []
        for group in case['required_document_evidence']:
            sets, notes = [], []
            for alt in group['alternatives']:
                eid = alt['evidence_id']
                ids = evidence_chunks[eid]
                relevant.update(ids)
                if eid == 'S3.2':
                    notes.append('Formula decoded successfully from PDF vector text layer.')
                sets.append(ids)
                topic = TOPICS[eid][1]
                # One curated query per requirement, not per alternative passage.
                if alt is group['alternatives'][0]:
                    existing = next((x for x in queries if x['query'] == topic), None)
                    if existing:
                        existing['requirement_ids'].append(group['requirement_id'])
                    else:
                        queries.append({'query': topic, 'requirement_ids': [group['requirement_id']]})
            groups.append({'requirement_id': group['requirement_id'], 'role': group['role'],
                           'sufficient_sets': sets, 'notes': notes,
                           'reference_alternatives': group['alternatives']})
        if len(groups) == 1:
            queries = [{'query': case['question'], 'requirement_ids': [groups[0]['requirement_id']]}]
        assert 1 <= len(queries) <= 6
        judgments[qid] = {'groups': groups, 'relevant_chunk_ids': sorted(relevant),
                         'review': 'Source and complete chunk text reviewed before retrieval runs; '
                                   'binary useful-context labels include partially sufficient evidence. '
                                   'Credit table positional lists are recoverable but row layout is degraded.'}
        plans[qid] = {'queries': queries, 'source_informed': True,
                      'db_dependent': case['is_database_needed'],
                      'note': 'Diagnostic only: source-informed topics, no reference database facts injected.'}
    return judgments, plans
