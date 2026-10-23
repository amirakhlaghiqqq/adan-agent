# Project-brief verification

These are demonstration and delivery checks for the original project brief,
separate from the earlier 12-case diagnostic benchmark.

- `responses.json`: eight actual HTTP responses from the rebuilt Compose API,
  including complete evidence, SQL/results, calculator calls and execution traces.
- `summary.json`: source/code/image fingerprints, cold-ingestion and index-reuse
  checks, scenario outcomes and source-preservation checks.
- `runtime-hashes.json`: confirms the running image contains the audited Python
  source files byte-for-byte.

Reproduce with the API running:

```bash
uv run python scripts/smoke.py --base-url http://localhost:8000 --scenario all \
  --pause-seconds 30 --output .cache/adan/task-smoke.json
```

Only free OpenRouter model endpoints are configured. The script sends questions
and visible context; reference facts and these checks are never supplied to the
agent. No external LLM judge is called. A mutation can be declined before SQL is
generated, so the offline tests separately force unsafe generated queries through
the real SQL guard. Requests are spaced by 30 seconds to reduce free-provider
rate-limit pressure. These eight examples establish the required demonstration
paths, not general accuracy over the benchmark.

This workstation required its optional outbound proxy for dependency downloads
and live provider calls. Cold ingestion used a fresh container and a separate new
Qdrant collection; index reuse was then checked with the same collection.
The application API uses the ordinary Compose network.

See the [requirement audit](../../../docs/REQUIREMENTS_AUDIT.md) for the full map
from the brief to implementation and validation evidence.

The earlier 12-question benchmark and its per-node assessment remain available
in [the representative CSV](../../agent-evaluation/2026-10-23-representative-12/node_assessments.csv)
and [the full Compose CSV](../../agent-evaluation/2026-10-23-compose/node_assessments.csv).
The `attempts/` directory retains the initial rate-label and billing-cycle failure
cases that led to the final guards.

Final outcome: **7/8 checks pass**. The aggregation response remains incorrect
(27937 versus 31984) because the model added unrequested filters. See
`summary.json`. The database and aggregation records were refreshed after the
final guards; the other six are earlier live responses from this audit.
