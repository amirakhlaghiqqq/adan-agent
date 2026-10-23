"""Pure metrics and paired parent-question bootstrap; no retrieval/model access."""
import math
import random
import statistics

CUTOFFS = (1, 3, 5, 10, 20)


def budget_allocations(n, budget=20):
    if not 1 <= n <= min(6, budget):
        raise ValueError('Expected 1 to 6 queries within candidate budget')
    return [budget // n + (i < budget % n) for i in range(n)]


def merge_rankings(rankings):
    output, seen = [], set()
    for ranking in rankings:
        for node in ranking:
            key = node['chunk_id']
            if key not in seen:
                seen.add(key)
                output.append(node)
    return output


def score(ranking, judgments, k):
    selected = ranking[:k]
    ids = {c['chunk_id'] for c in selected}
    relevant = set(judgments['relevant_chunk_ids'])
    groups = judgments['groups']
    covered = [g['requirement_id'] for g in groups
               if any(set(s) <= ids for s in g['sufficient_sets'])]
    gains = [int(c['chunk_id'] in relevant) for c in selected]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(k, len(relevant))))
    return {'evidence_recall': len(covered) / len(groups),
            'all_evidence_success': int(len(covered) == len(groups)),
            'context_precision': sum(gains) / len(selected) if selected else None,
            'ndcg': dcg / ideal if ideal else None, 'returned_count': len(selected),
            'covered_requirements': covered}


def mean(values):
    values = [v for v in values if v is not None]
    return statistics.mean(values) if values else None


def paired_interval(deltas, rounds=2000):
    # Sample question IDs, preserving paired observations and all configurations.
    rng = random.Random(20261023)
    values = list(deltas)
    if not values:
        return None
    draws = sorted(mean(rng.choices(values, k=len(values))) for _ in range(rounds))
    return {'delta': mean(values), 'ci95': [draws[int(.025 * rounds)],
                                          draws[int(.975 * rounds)]], 'n': len(values)}
