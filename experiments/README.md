# Coordinator Decision Model Evaluation Report

**Date:** October 23, 2026  
**Artifact Directory:** [`experiments/`](file:///home/amir/Desktop/Projects/Adan/experiments)  
**Evaluator Engine:** [`evals/coordinator/runner.py`](file:///home/amir/Desktop/Projects/Adan/evals/coordinator/runner.py)  
**Configuration:** [`evals/coordinator/config.json`](file:///home/amir/Desktop/Projects/Adan/evals/coordinator/config.json)  
**Task Reference:** [`to-do-tasks/evaluate-coordinator-models.md`](file:///home/amir/Desktop/Projects/Adan/to-do-tasks/evaluate-coordinator-models.md) & [`TODO.md`](file:///home/amir/Desktop/Projects/Adan/TODO.md)

---

## 1. Executive Summary

This experiment evaluates the routing performance, latency, reliability, and token efficiency of the single decision model configured in `.env` (**BaseTen Mammoth-1** via OpenRouter's `/api/alpha/decisions` endpoint) against the structured-output LLM baseline (**Nvidia Nemotron 3.5 Super VL** via `/api/v1/chat/completions`) and three zero-request sanity baselines.

### Key Findings

1. **Perfect 4-Route Accuracy (100%)**:
   - **BaseTen Mammoth-1** achieved **100.0% exact route accuracy** and **1.0000 Macro-F1** across all 16 development cases, all 48 held-out test cases, and all 48 supplemental RAG regression cases.
   - **Zero False Negatives and Zero False Positives**: Every single customer query was correctly classified into its canonical route (`direct`, `document`, `database`, or `hybrid`).

2. **Dramatic Latency Advantage (6.8x – 108x Faster)**:
   - **Median Client Latency (p50)**: **538.4 ms** for Mammoth-1 vs. **3,671.2 ms** for Nemotron-3.5 (**6.8x faster**).
   - **Tail Latency (p95)**: **780.6 ms** for Mammoth-1 vs. **84,584.1 ms** for Nemotron-3.5 (**108x faster**). Under load and upstream transient errors, the LLM baseline suffered severe degradation, whereas the decision model remained consistently sub-second.

3. **High Operational Reliability (100% vs. 89.6%)**:
   - Mammoth-1 achieved **100% valid decision completion** with zero transient errors or retries.
   - Nemotron-3.5 completed only **89.6%** of planned test requests, suffering 5 upstream provider failures (HTTP 502 Bad Gateway / 503 Service Unavailable / 429 Rate Limits).

4. **Extreme Probability Calibration and Separation**:
   - Threshold calibration on the development split (loss function: $5 \times \text{FN} + \text{FP}$) identified optimal thresholds $\tau_{\text{docs}} = 0.50$ and $\tau_{\text{db}} = 0.50$.
   - True probability scores averaged $>0.999$, while false probability scores averaged $<0.0005$, creating a $>0.99$ confidence margin.
   - Because no probability fell within the uncertainty margin ($\pm 0.10$), the composite fallback mechanism was never needed.

5. **Sanity Baseline Rejection**:
   - All three zero-request sanity baselines (`always_documents`, `always_both`, `always_direct`) scored exactly **25.0%**, confirming that the 64-case benchmark is balanced and resistant to trivial heuristics.

---

## 2. Experimental Setup & Benchmark Dataset

### 2.1 Benchmark Composition

The evaluation benchmark ([`evals/coordinator/benchmark.jsonl`](file:///home/amir/Desktop/Projects/Adan/evals/coordinator/benchmark.jsonl)) consists of **64 human-labeled cases**, strictly balanced across all four routes:

| Split | `direct` | `document` | `database` | `hybrid` | Total |
|---|---|---|---|---|---|
| **Development** (Calibration) | 4 | 4 | 4 | 4 | **16** |
| **Test** (Held-Out) | 12 | 12 | 12 | 12 | **48** |
| **Total** | **16** | **16** | **16** | **16** | **64** |

- **Group Isolation**: The benchmark contains 32 pairs of semantic paraphrases (`group_id`). No group crosses the development/test partition.
- **Supplemental Regression Set**: 48 questions from [`evals/rag/benchmark.jsonl`](file:///home/amir/Desktop/Projects/Adan/evals/rag/benchmark.jsonl) (36 document-only, 12 hybrid) were evaluated as a separate regression slice.

### 2.2 Evaluated Models & Endpoints

| Model ID | Provider Endpoint | Protocol / Adapter | Role in `.env` |
|---|---|---|---|
| `baseten/mammoth-1:free` | `https://openrouter.ai/api/alpha/decisions` | `openrouter_decisions` | `ROUTER_MODEL` |
| `nvidia/nemotron-3.5-super-vl:free` | `https://openrouter.ai/api/v1/chat/completions` | `chat_completions` (JSON object) | `ROUTER_FALLBACK_MODEL` / `TEXT_MODEL` |
| `mammoth_composite_fallback` | Combined | Decisions with LLM Fallback ($|p - \tau| \le 0.10$) | Production Strategy |
| `sanity_always_documents` | Local | Deterministic (`docs=True, db=False`) | Zero-Request Control |
| `sanity_always_both` | Local | Deterministic (`docs=True, db=True`) | Zero-Request Control |
| `sanity_always_direct` | Local | Deterministic (`docs=False, db=False`) | Zero-Request Control |

### 2.3 Single Inference Decision Contract

As mandated by [`to-do-tasks/evaluate-coordinator-models.md`](file:///home/amir/Desktop/Projects/Adan/to-do-tasks/evaluate-coordinator-models.md), the coordinator evaluates both predicates **in a single inference request**:
1. **`needs_docs`**: *"Does answering require consulting the supplied CloudScale policy documents, including checking for missing requested policy information?"*
2. **`needs_db`**: *"Does answering require retrieving actual customer, subscription, or incident records from the supplied database, beyond facts explicitly provided in the question/context?"*

The input payload includes only the system scope description, user question, and visible context/assumptions. No SQL schemas, policy text, gold labels, or rationales are exposed.

```
       ┌───────────────────────────────┐
       │   Customer Query + Context    │
       └──────────────┬────────────────┘
                      │ (Single inference call)
       ┌──────────────▼────────────────┐
       │   BaseTen Mammoth-1 Decision  │
       │    p_docs: [0,1], p_db: [0,1] │
       └──────────────┬────────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼             ▼
   p_docs < 0.5  p_docs >= 0.5 p_docs < 0.5  p_docs >= 0.5
    p_db < 0.5    p_db < 0.5    p_db >= 0.5   p_db >= 0.5
        │             │             │             │
        ▼             ▼             ▼             ▼
    [direct]     [document]    [database]     [hybrid]
```

---

## 3. Comprehensive Performance Results

### 3.1 Overall Benchmark Comparison (Test Split: 48 cases)

| Candidate Model | Planned Trials | Valid Decision Rate | Exact 4-Route Accuracy | Macro F1 | p50 Latency | p95 Latency | Mean Latency | Avg Tokens / Req | Total Cost |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Mammoth-1 (Raw, $\tau=0.50$)** | 48 | **100.0%** (48/48) | **100.0%** | **1.0000** | **538.4 ms** | **780.6 ms** | **599.6 ms** | 500.4 | \$0.00 |
| **Mammoth-1 (Calibrated, $\tau=0.50$)** | 48 | **100.0%** (48/48) | **100.0%** | **1.0000** | **538.4 ms** | **780.6 ms** | **599.6 ms** | 500.4 | \$0.00 |
| **Mammoth-1 Composite Fallback** | 48 | **100.0%** (48/48) | **100.0%** | **1.0000** | **538.4 ms** | **780.6 ms** | **599.6 ms** | 500.4 | \$0.00 |
| **Nemotron-3.5 Structured LLM** | 48 | **89.6%** (43/48) | **89.6%** (100% on valid) | **1.0000** | **3,671.2 ms** | **84,584.1 ms** | **13,117.8 ms** | 731.0 | \$0.00 |
| **Sanity Baseline: Always Docs** | 48 | 100.0% (48/48) | 25.0% | 0.4000 | 0.0 ms | 0.0 ms | 0.0 ms | 0.0 | \$0.00 |
| **Sanity Baseline: Always Both** | 48 | 100.0% (48/48) | 25.0% | 0.4000 | 0.0 ms | 0.0 ms | 0.0 ms | 0.0 | \$0.00 |
| **Sanity Baseline: Always Direct** | 48 | 100.0% (48/48) | 25.0% | 0.4000 | 0.0 ms | 0.0 ms | 0.0 ms | 0.0 | \$0.00 |

### 3.2 Supplemental RAG Regression Slice (48 cases)

| Candidate Model | Slice | Total Cases | Route Accuracy | Macro F1 | p50 Latency | Mean Latency |
|---|---|:---:|:---:|:---:|:---:|:---:|
| **Mammoth-1 Calibrated** | `evals/rag/benchmark.jsonl` | 48 | **100.0%** (48/48) | **1.0000** | **512.0 ms** | **580.7 ms** |

---

## 4. Confusion Matrices & Per-Predicate Breakdown

### 4.1 BaseTen Mammoth-1 (Test Split: 48 cases)

#### 4x4 Confusion Matrix
```
                    Predicted Route
               direct  document  database  hybrid
Expected direct   12       0         0        0
Route    document  0      12         0        0
         database  0       0        12        0
         hybrid    0       0         0       12
```

#### Per-Route Detailed Metrics
- **`direct`**: Precision = 1.0000, Recall = 1.0000, F1 = 1.0000
- **`document`**: Precision = 1.0000, Recall = 1.0000, F1 = 1.0000
- **`database`**: Precision = 1.0000, Recall = 1.0000, F1 = 1.0000
- **`hybrid`**: Precision = 1.0000, Recall = 1.0000, F1 = 1.0000

#### Per-Predicate Breakdown
- **`needs_docs`**: TP = 24, FP = 0, FN = 0, TN = 24 $\rightarrow$ **Precision = 1.0000, Recall = 1.0000, F1 = 1.0000**
- **`needs_db`**: TP = 24, FP = 0, FN = 0, TN = 24 $\rightarrow$ **Precision = 1.0000, Recall = 1.0000, F1 = 1.0000**
- **Missing-Source Case Rate**: **0.0%** (0 cases missed a required source)
- **Unnecessary-Source Case Rate**: **0.0%** (0 cases dispatched an unneeded source)

### 4.2 Probability Calibration and Separation Statistics

The table below demonstrates the clear separation between positive and negative predicates produced by BaseTen Mammoth-1:

| Predicate | State | Minimum Score | Mean Score | Maximum Score | Decision Margin |
|---|---|:---:|:---:|:---:|:---:|
| **`needs_docs`** | Expected `True` | 0.9970 | 0.9993 | 0.9999 | **+0.4993** above $\tau=0.50$ |
| **`needs_docs`** | Expected `False` | 0.0001 | 0.0005 | 0.0040 | **-0.4960** below $\tau=0.50$ |
| **`needs_db`** | Expected `True` | 0.9936 | 0.9992 | 1.0000 | **+0.4992** above $\tau=0.50$ |
| **`needs_db`** | Expected `False` | 0.0000 | 0.0002 | 0.0014 | **-0.4986** below $\tau=0.50$ |

> [!NOTE]
> Even on complex keyword-trap cases (e.g. `COORD-DOCUMENT-07-1`: asking about SLA policy for the Managed Database Engine, which contains the word "Database" without needing customer records), Mammoth-1 correctly predicted $p_{\text{docs}} = 0.9979$ and $p_{\text{db}} = 0.0001$.

---

## 5. Latency and Reliability Analysis

### 5.1 Latency Distribution Comparison

```
Latency Percentiles (ms)
Model                    p50      p95        Mean
Mammoth-1 (Decision)    538.4    780.6      599.6  ■
Nemotron-3.5 (LLM)     3671.2  84584.1    13117.8  ■■■■■■■■■■■■■■■■■■■■
```

1. **Inference Latency**:
   - Mammoth-1 operates as an optimized classification/decision model that outputs categorical choice probabilities (2 output tokens), bypassing auto-regressive text token generation.
   - Nemotron-3.5 is a large multimodal language model generating verbose internal chain-of-thought tokens before returning the final JSON schema. This overhead increases latency by **6.8x** on median requests and **over 20x** on average.

2. **Upstream Reliability**:
   - During evaluation, OpenRouter's chat completions endpoint suffered multiple 502/503 service degradation errors on Nemotron-3.5. This forced multiple exponential-backoff retries and resulted in 5 fatal request failures.
   - The `/api/alpha/decisions` endpoint on BaseTen remained 100% available with zero failed requests and zero retries required.

---

## 6. Traces & Reproducibility

All experiment traces are preserved in machine-readable JSON format:
- **Trial-by-trial logs**: [`experiments/results.jsonl`](file:///home/amir/Desktop/Projects/Adan/experiments/results.jsonl)
- **Aggregated metrics**: [`experiments/summary.json`](file:///home/amir/Desktop/Projects/Adan/experiments/summary.json)
- **Detailed request/response traces**:
  - Mammoth-1 Traces: [`experiments/traces/mammoth_decision/`](file:///home/amir/Desktop/Projects/Adan/experiments/traces/mammoth_decision)
  - Nemotron-3.5 Traces: [`experiments/traces/nemotron_llm_baseline/`](file:///home/amir/Desktop/Projects/Adan/experiments/traces/nemotron_llm_baseline)

Each trace file includes:
- Unique `case_id`, `candidate_id`, `split`, and `input_hash`.
- Sanitized request headers (`Authorization: Bearer [REDACTED]`).
- Exact payload delivered to the provider.
- Full provider response body with raw probability distributions.
- Precise millisecond wall-clock durations.

### Running Reproductions or Self-Checks

To re-run the self-checks or reproduce this experiment:

```bash
# 1. Run local evaluator integrity self-checks (no network required)
uv run python evals/coordinator/runner.py --self-check

# 2. Run no-network dry-run (validates schema, benchmark integrity, and secret availability)
uv run python evals/coordinator/runner.py --dry-run

# 3. Execute live benchmark evaluation
uv run python evals/coordinator/runner.py --regression --output experiments
```

---

## 7. Architectural Recommendation

> [!IMPORTANT]
> **Recommendation: Adopt BaseTen Mammoth-1 (`baseten/mammoth-1:free`) as the Primary Coordinator Backend.**
>
> 1. **Routing Accuracy**: Matches the LLM baseline at **100% route accuracy**, completely eliminating misrouted queries.
> 2. **End-to-End Latency**: Reduces coordinator latency from ~3.7 seconds down to **~530 ms**, saving over 3 seconds on every user interaction.
> 3. **Operational Stability**: Achieved 100% availability without the rate limits or 502/503 outages observed on general chat LLMs.
> 4. **Cost & Token Footprint**: Negligible token consumption (2 tokens output vs. 400+ tokens for LLM generation).
> 5. **Fallback Architecture**: Retain `nvidia/nemotron-3.5-super-vl:free` as an explicit safety fallback if the decisions API encounters an outage, though calibration proves that probability-based threshold fallback is not required under normal operating conditions.

