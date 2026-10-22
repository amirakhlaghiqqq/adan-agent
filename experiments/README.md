# Coordinator Decision Model Evaluation Report

**Date:** October 23, 2026  
**Artifact Directory:** [`experiments/`](file:///home/amir/Desktop/Projects/Adan/experiments)  
**Evaluator Engine:** [`evals/coordinator/runner.py`](file:///home/amir/Desktop/Projects/Adan/evals/coordinator/runner.py)  
**Configuration:** [`evals/coordinator/config.json`](file:///home/amir/Desktop/Projects/Adan/evals/coordinator/config.json)  
**Task Reference:** [`to-do-tasks/evaluate-coordinator-models.md`](file:///home/amir/Desktop/Projects/Adan/to-do-tasks/evaluate-coordinator-models.md) & [`TODO.md`](file:///home/amir/Desktop/Projects/Adan/TODO.md)

---

## 1. Executive Summary

This experiment evaluates the routing performance, latency, reliability, calibration, and token efficiency of single decision models against a structured-output LLM baseline and three sanity controls.

Evaluated candidates:
1. **BaseTen Mammoth-1 (`baseten/mammoth-1:free`)**: The primary decision model configured in `.env`.
2. **BaseTen Elephant-1 (`baseten/elephant-1:free`)**: Alternative decision model tested via `/api/alpha/decisions`.
3. **Nvidia Nemotron 3.5 Super VL (`nvidia/nemotron-3.5-super-vl:free`)**: Structured-output LLM baseline from `.env`.
4. **Composite Fallback**: Mammoth-1 decision model backed by Nemotron fallback for borderline confidence or API failure.
5. **Sanity Baselines**: Zero-request controls (`always_documents`, `always_both`, `always_direct`).

---

## 2. Head-to-Head Benchmark Results

### 2.1 Held-Out Test Split (48 Balanced Cases)

The test set contains 12 cases each for `direct`, `document`, `database`, and `hybrid` routes:

| Candidate Model | Architecture / Protocol | Valid Decision Rate | Exact 4-Route Accuracy | Macro F1 | **p50 Latency** | **p95 Latency** | **Mean Latency** | Avg Tokens / Decision |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **BaseTen Mammoth-1 (Calibrated)** | Single Decision (`/api/alpha/decisions`) | **100.0%** (48/48) | **100.0%** | **1.0000** | **538.4 ms** | **780.6 ms** | **599.6 ms** | 500.4 |
| **BaseTen Elephant-1 (Calibrated)** | Single Decision (`/api/alpha/decisions`) | **100.0%** (48/48) | **100.0%** | **1.0000** | **496.3 ms** | **1,358.9 ms** | **611.7 ms** | 500.5 |
| **BaseTen Mammoth-1 (Raw, $\tau=0.5$)** | Single Decision (`/api/alpha/decisions`) | **100.0%** (48/48) | **100.0%** | **1.0000** | **538.4 ms** | **780.6 ms** | **599.6 ms** | 500.4 |
| **BaseTen Elephant-1 (Raw, $\tau=0.5$)** | Single Decision (`/api/alpha/decisions`) | **100.0%** (48/48) | **100.0%** | **1.0000** | **496.3 ms** | **1,358.9 ms** | **611.7 ms** | 500.5 |
| **Mammoth-1 Composite Fallback** | Decision + LLM Fallback ($|p-\tau| \le 0.10$) | **100.0%** (48/48) | **100.0%** | **1.0000** | **538.4 ms** | **780.6 ms** | **599.6 ms** | 500.4 |
| **Nvidia Nemotron 3.5 Super VL** | Structured LLM (`chat/completions`) | **89.6%** (43/48) | **89.6%** *(100% on valid)* | **1.0000** | **3,671.2 ms** | **84,584.1 ms** | **13,117.8 ms** | 731.0 |
| **Sanity Baseline: Always Docs** | Zero-Request Control | 100.0% (48/48) | 25.0% | 0.4000 | 0.0 ms | 0.0 ms | 0.0 ms | 0.0 |
| **Sanity Baseline: Always Both** | Zero-Request Control | 100.0% (48/48) | 25.0% | 0.4000 | 0.0 ms | 0.0 ms | 0.0 ms | 0.0 |
| **Sanity Baseline: Always Direct** | Zero-Request Control | 100.0% (48/48) | 25.0% | 0.4000 | 0.0 ms | 0.0 ms | 0.0 ms | 0.0 |

---

### 2.2 Development Calibration Split (16 Cases) & Threshold Optimization

Calibration searched thresholds in $[0.20, 0.80]$ with step $0.05$ to minimize $5 \times \text{False Negatives} + \text{False Positives}$ per predicate:

| Model Candidate | Dev Accuracy ($\tau=0.50$) | Dev Accuracy (Calibrated) | Optimal $\tau_{\text{docs}}$ | Optimal $\tau_{\text{db}}$ | Calibration Rationale |
|---|:---:|:---:|:---:|:---:|---|
| **BaseTen Mammoth-1** | **100.0%** (16/16) | **100.0%** (16/16) | **0.50** | **0.50** | Perfect separation across all thresholds $[0.20, 0.70]$ ($L=0$). Default 0.50 selected by tie-breaker. |
| **BaseTen Elephant-1** | **93.8%** (15/16) | **100.0%** (16/16) | **0.50** | **0.40** | Elephant-1 gave $p_{\text{db}} = 0.4099$ on `COORD-HYBRID-02-2`. Lowering $\tau_{\text{db}}$ to $0.40$ eliminated the false negative ($L: 5 \rightarrow 0$). |
| **Nemotron-3.5 LLM** | **93.8%** *(100% on valid)* | N/A (Boolean output) | N/A | N/A | Suffered 1 server 502 error during dev run. Native Boolean decision. |

---

### 2.3 Supplemental RAG Regression Slice (48 Cases)

Evaluated against all 48 questions from [`evals/rag/benchmark.jsonl`](file:///home/amir/Desktop/Projects/Adan/evals/rag/benchmark.jsonl) (36 document-only, 12 hybrid):

| Model Candidate | Exact Route Accuracy | Macro F1 | p50 Latency | Mean Latency | Error Breakdown |
|---|:---:|:---:|:---:|:---:|---|
| **BaseTen Mammoth-1** | **100.0%** (48/48) | **1.0000** | **512.0 ms** | **580.7 ms** | 0 errors. All 36 document and 12 hybrid cases classified correctly. |
| **BaseTen Elephant-1** | **97.9%** (47/48) | **0.9714** | **496.9 ms** | **579.9 ms** | 1 False Negative: `X-E03` (hybrid) predicted $p_{\text{db}} = 0.2738 < 0.40$, misrouted to `document`. |

---

## 3. Detailed Comparison: Mammoth-1 vs. Elephant-1

### 3.1 Probability Distribution & Confidence Separation

| Predicate | Condition | Mammoth-1 ($p$ range) | Elephant-1 ($p$ range) | Advantage |
|---|---|:---:|:---:|:---:|
| **`needs_docs`** | When `True` | **0.9970 – 0.9999** | **0.9720 – 0.9998** | Mammoth-1 (higher confidence) |
| **`needs_docs`** | When `False` | **0.0001 – 0.0040** | **0.0001 – 0.0120** | Mammoth-1 (lower false positive risk) |
| **`needs_db`** | When `True` | **0.9936 – 1.0000** | **0.2738 – 0.9999** | **Mammoth-1 (much more robust)** |
| **`needs_db`** | When `False` | **0.0000 – 0.0014** | **0.0000 – 0.0062** | Mammoth-1 |

> [!WARNING]
> **Elephant-1 Vulnerability on Hybrid Queries**:
> On certain multi-faceted requests (such as `COORD-HYBRID-02-2` and `X-E03`), Elephant-1 assigns lower probability to the database predicate ($p_{\text{db}} \approx 0.27 - 0.41$). At the default threshold ($\tau=0.5$), this causes false negatives where hybrid queries get misrouted to `document`-only. Mammoth-1 consistently scores $p_{\text{db}} > 0.993$ on all hybrid queries, showing no predicate degradation.

### 3.2 Latency Comparison

- **Median Latency (p50)**: Elephant-1 is marginally faster (**496.3 ms** vs. **538.4 ms**).
- **Tail Latency (p95)**: Mammoth-1 is significantly more consistent (**780.6 ms** vs. **1,358.9 ms**).

---

## 4. Traces & Audit Artifacts

Execution traces for all candidates are persisted under `experiments/traces/`:
- **Mammoth-1 Traces**: [`experiments/traces/mammoth_decision/`](file:///home/amir/Desktop/Projects/Adan/experiments/traces/mammoth_decision)
- **Elephant-1 Traces**: [`experiments/traces/elephant_decision/`](file:///home/amir/Desktop/Projects/Adan/experiments/traces/elephant_decision)
- **Nemotron-3.5 Traces**: [`experiments/traces/nemotron_llm_baseline/`](file:///home/amir/Desktop/Projects/Adan/experiments/traces/nemotron_llm_baseline)

All trial outputs and machine-readable statistics are available in [`experiments/results.jsonl`](file:///home/amir/Desktop/Projects/Adan/experiments/results.jsonl) and [`experiments/summary.json`](file:///home/amir/Desktop/Projects/Adan/experiments/summary.json).

---

## 5. Architectural Recommendation

> [!IMPORTANT]
> **Final Recommendation:**
> 1. **Primary Coordinator:** **BaseTen Mammoth-1 (`baseten/mammoth-1:free`)** remains the best-in-class choice:
>    - 100% accuracy across all test, dev, and regression suites without needing customized threshold tuning.
>    - Superior tail latency (780.6 ms p95).
>    - Unshakeable database predicate discrimination on hybrid questions.
> 2. **Alternative Fast Option:** **BaseTen Elephant-1 (`baseten/elephant-1:free`)** is a viable lightweight alternative if median latency is paramount (saving ~40 ms), provided the database threshold is calibrated to $\tau_{\text{db}} \le 0.35 - 0.40$ to avoid hybrid false negatives.
> 3. **Fallback Coordinator:** Retain `nvidia/nemotron-3.5-super-vl:free` strictly as a failover backend for API connection or provider outages.
