# Evaluate the Compose agent

Start the real application with `docker compose up -d --build` and wait for
`http://127.0.0.1:8000/health`. Validate the frozen benchmark before collection:

```bash
uv run python evals/rag/validate_benchmark.py --self-check
```

`scripts/evaluate_agent.py` calls the ordinary FastAPI endpoint and saves a full
request/response/trace per question. It sends only `question` and `input_context`;
the answer key remains in the external evaluator. `--phase collect` saves runs,
`--phase assess` assesses existing runs, and `--phase all` does both. Existing
responses with identical inputs are reused. Judge results are cached by the exact
model/instructions/input/schema hash. Collection uses the configured free agent
models. The final selected run uses **Luna subagents (gpt-6-luna)**, dispatched
as three parallel batches, for its 26 structured semantic judgments.

The selected run has 12 cases: four document questions, four hybrid questions,
and four routing cases (one per route). The selection covers policy lookup,
support commitments, credit boundaries, absent pricing, SQL facts, leap-year
arithmetic, cohort totals, deadlines, and keyword traps. It is a small diagnostic
sample rather than a statistically calibrated estimate of the full bank.

```bash
uv run python scripts/evaluate_agent.py \
  --phase collect --concurrency 1 --pause-seconds 3 \
  --output experiments/agent-evaluation/2026-10-23-representative-12 \
  --only rag:E01 rag:E08 rag:M10 rag:H06 \
    rag:X-E01 rag:X-M01 rag:X-H01 rag:X-H04 \
    coordinator:COORD-DOCUMENT-07-1 coordinator:COORD-DATABASE-08-1 \
    coordinator:COORD-HYBRID-08-1 coordinator:COORD-DIRECT-07-2
```

The Luna jobs and raw judgments are saved in `luna_jobs/` and `luna_results/`.
Rebuild the final CSV without any model/API calls:

```bash
uv run python scripts/assemble_luna_evaluation.py \
  --output experiments/agent-evaluation/2026-10-23-representative-12
```

Use a fresh output directory for a new trial. The earlier `agy` assessment
backend remains in `evaluate_agent.py --phase assess`; its quota-limited results
are audit-only and are excluded from the final Luna report.

Outputs in the selected run directory:

- `node_assessments.csv`: one question per row, node diagnostics in 0–1 columns,
  separate 0–2 judge criteria, timing, model/configuration and trace links.
- `runs/{suite}/{question_id}.json`: exact inputs, full agent output, HTTP status,
  execution histories, usage and collection errors.
- `assessments/`: checks, judge reasons and score exclusions per question.
- `luna_jobs/`, `luna_results/`, `luna_judges/`: exact job inputs/schema, raw Luna
  judgments and validated records with input hashes. `luna_dispatch.json`
  records the three parallel worker assignments. Earlier `judges/` files are
  excluded Antigravity audit records, not final scores.
- `selection.json`, dataset snapshots, `environment.json`, `corpus.json`,
  `retrieval_annotations.json`, `assessment_config.json`: selection and provenance.
- `summary.json`, `REPORT.md`, `checksums.json`: denominators, interpretation,
  limitations and SHA-256 integrity records.

The routing-only dataset has reference labels for coordinator decisions. Other
node scores for those cases are `NO_REFERENCE`, except the independently
checkable output formatter contract. The RAG dataset supports source, SQL,
calculator and answer assessment. Skipped, unavailable and failed-judge checks
remain explicit. Provider failures are excluded from affected node-score means;
agent mistakes and exhausted work budgets remain observed outcomes.

These are diagnostics within complete end-to-end runs, so upstream failures can
affect downstream results. This does not implement the isolated retrieval and
generation modes in [the evaluation contract](../docs/EVALUATION.md).
