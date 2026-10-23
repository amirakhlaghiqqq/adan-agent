# Implementation and validation

The implemented workflow is described in [ARCHITECTURE.md](ARCHITECTURE.md).
The [requirement audit](REQUIREMENTS_AUDIT.md) maps the supplied project brief to
code, tests and saved Docker responses.

## Reproduce the checks

```bash
uv sync --frozen
uv run pytest -q
uv run ruff check src tests scripts evals/agent_assessment.py evals/agent_judge.py
uv run ruff format --check src tests scripts evals/agent_assessment.py evals/agent_judge.py
docker compose config --quiet
bash -n docker-entrypoint.sh
```

Tests use scripted model responses and mock dense embeddings to avoid network
calls. They execute the real graph, API, SQLite queries/security checks,
calculator, Markdown preprocessing and Qdrant persistence. They check routing
fallback, parallel request isolation, malformed tool arguments, SQL repair,
partial acquisition, citation rejection, correction exhaustion, rate-limit
backoff and deadline handling. These tests do not measure live LLM accuracy or
run Docling's model downloads and PDF layout inference.

With the Compose API running, verify the required live scenarios and save the
full responses:

```bash
uv run python scripts/smoke.py --base-url http://localhost:8000 --scenario all \
  --pause-seconds 30 --output .cache/adan/task-smoke.json
```

This runs two document questions, a database join, a filtered aggregation, SQL
followed by a real calculator call, a hybrid question, an out-of-corpus question
and a mutation request. The script saves responses before checking outcomes and
returns a nonzero exit code if a scenario fails. The live model may decline a
mutation before producing SQL; deterministic security tests separately force
dangerous generated SQL through the actual execution guard.

## Data preparation

Two policy PDFs and their editable LaTeX sources are in `data/documents/`.
`data/database/app.db` contains 30 customers and linked subscriptions/incidents.
The supplied `schema.sql` and `seed_data.sql` reproduce this snapshot. Application
startup creates a missing configured database without resetting an existing one.
`data/database/seed_db.py` is an explicit destructive reset utility; ordinary
startup does not call it.

The Docker entrypoint runs `scripts/ingest.py --ensure`: it reuses a matching
index or parses/embeds the PDFs if the versioned collection is absent, then
audits the active collection. A normal restart does not re-embed all documents.
For a deliberate re-ingestion, use `uv run python scripts/ingest.py`.

## Evaluation and limitations

The external evaluation runner and saved Luna assessments are documented in
[evals/README.md](../evals/README.md) and
[the 12-case report](../experiments/agent-evaluation/2026-10-23-representative-12/REPORT.md).
That purposive diagnostic sample predates the latest recovery changes. It is
not a fresh benchmark measurement of this revision. No Nemotron judge is used in
its final scores. Isolated retrieval/generation evaluation modes remain planned.

Free provider endpoints can be unavailable, rate-limited or return malformed
tool calls. The requested Mammoth routing model failed with HTTP 400 in earlier
runs; the configured free fallback is recorded explicitly. Generation and
model-assisted verification can still make mistakes. The SQL output carries no
currency column, so monetary database values must be reported as currency units
unless the question supplies a currency assumption.

The supplied SLA has conflicting Starter-tier wording: its tier description
denies an uptime guarantee while the availability table lists a target. Answers
must acknowledge that conflict when relevant. Missing policy terms and missing
database records must not be invented.

This prototype has no authentication, tenancy authorization, streaming API or
durable multi-turn replay. Embedded Qdrant permits one process per storage path;
use the Compose Qdrant server for concurrent application processes. First-time
ingestion requires internet access for Docling/BM25 model assets and provider
embeddings. There is no requirement for production deployment or a GPU.
