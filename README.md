# adan-agent (CloudScale Assistant)

A runnable LangGraph assistant for the [Adan task](TASK_SPECIFICATION.md). It answers
policy questions from the two supplied PDFs, generates read-only SQLite queries,
uses a real arithmetic/calendar calculator, and returns the answer with evidence
and an execution trace through FastAPI.

## Run locally

Use Python 3.12, [uv](https://docs.astral.sh/uv/), and `pdftotext` (Ubuntu/Debian:
`sudo apt-get install poppler-utils`). Run commands from the repository root.

```bash
uv sync --frozen
cp .env.example .env
```

Set `OPENROUTER_API_KEY` in `.env` or export it in your shell. The example contains
no credentials. Then start the application:

```bash
uv run uvicorn adan.api:app --host 127.0.0.1 --port 8000 --loop asyncio
```

Startup checks the database and creates it from the supplied SQL files only if
it is missing. Existing databases are preserved. It extracts the policy PDFs,
loads local FastEmbed embeddings, and creates or reopens a persistent Qdrant
index. The first launch downloads the embedding model and can take a few minutes.

Open <http://127.0.0.1:8000/> for the web UI or
<http://127.0.0.1:8000/docs> for the API explorer. Health is available at
`GET /health` after startup finishes.

```bash
curl http://127.0.0.1:8000/api/v1/query \
  -H 'Content-Type: application/json' \
  -d '{"question":"Which payment methods does CloudScale accept? Cite the policy.","input_context":[]}'
```

The request accepts `question` and optional `input_context` (a list of visible
assumptions/instructions). Empty questions and oversized inputs return HTTP 422.
Responses contain `answer`, `status`, `stop_reason`, `citations`, `route`, raw
`retrieval_calls`/`database_calls`, `tool_calls`, exact `generator_contexts`,
`guardrail_history`, `aggregation_artifacts`, and `execution_trace`.
An interrupted or unavailable acquisition remains explicit in the trace. A
captured system failure can return HTTP 200 with a qualified result, so inspect
`status` and `stop_reason` as well as the HTTP status.

For benchmark assessment, responses also expose `retrieved_document_chunks`,
`database_results`, `calculator_trace`, `failures`, `timings`, and `usage`, with
`schema_version: "1.0"` and `mode: "end_to_end"`. See the
[output contract and collection example](docs/EVALUATION_OUTPUT.md) for matching
these fields to `evals/rag/benchmark.jsonl` without passing answer keys to the agent.

## Demonstration Scenarios & Sample Outputs

The system fulfills all demonstration requirements specified in the project brief (RAG, NL2SQL, Multi-step Tool Calling, Out-of-Scope Handling, and SQL Security Guards):

### 1. Document RAG (2 Scenarios)
**Scenario 1.1 — Billing & Payment Methods:**
```bash
curl -s http://127.0.0.1:8000/api/v1/query -H 'Content-Type: application/json' \
  -d '{"question":"Which payment methods does CloudScale accept? Cite the policy."}'
```
*Output snippet:*
```json
{
  "status": "complete",
  "route": {"needs_docs": true, "needs_db": false},
  "answer": "CloudScale accepts electronic bank transfers (ACH in the US, SEPA in the EU), major credit cards (Visa, MasterCard, American Express), and wire transfers for annual invoices exceeding $10,000 (Section 2.1).",
  "citations": [
    {"chunk_id": "...", "document_id": "DOC-BIL-2024-V3", "section": "2. Invoicing, Payment Methods & Net Terms / 2.1 Approved Payment Methods"}
  ]
}
```

**Scenario 1.2 — SLA Availability & Uptime Commitments:**
```bash
curl -s http://127.0.0.1:8000/api/v1/query -H 'Content-Type: application/json' \
  -d '{"question":"What is the guaranteed Monthly Uptime Percentage for Enterprise tier, and what credit applies below 99.0%?"}'
```
*Output snippet:*
```json
{
  "status": "complete",
  "route": {"needs_docs": true, "needs_db": false},
  "answer": "For the Enterprise tier, CloudScale commits to a Monthly Uptime Percentage of at least 99.99% (Section 3.1). If uptime falls below 99.00%, eligible customers receive a 50% service credit for 98.00%–99.00%, and up to a 100% service credit if availability drops below 95.00% (Section 4.2).",
  "citations": [
    {"chunk_id": "...", "document_id": "DOC-SLA-2024-V2", "section": "3. Service Availability & Uptime Commitments / 3.1 Monthly Availability Commitments"},
    {"chunk_id": "...", "document_id": "DOC-SLA-2024-V2", "section": "4. Service Credit Structure / 4.2 Service Credit Brackets"}
  ]
}
```

### 2. Natural Language to SQL (2 Scenarios)
**Scenario 2.1 — Multi-table Join & Filtering:**
```bash
curl -s http://127.0.0.1:8000/api/v1/query -H 'Content-Type: application/json' \
  -d '{"question":"List the three companies with the highest subscription monthly_rate, including plan names and raw rates."}'
```
*Output snippet:*
```json
{
  "status": "complete",
  "route": {"needs_docs": false, "needs_db": true},
  "database_calls": [{
    "sql": "SELECT c.company_name, s.plan_name, s.monthly_rate FROM customers c JOIN subscriptions s ON c.customer_id = s.customer_id ORDER BY s.monthly_rate DESC LIMIT 3;"
  }],
  "answer": "The three companies with the highest monthly rates are:\n1. Apex Global Logistics (Enterprise Scale, $3,200.00/mo)\n2. Quantum HyperScale (Enterprise Elite, $2,850.00/mo)\n3. Vortex Streaming Media (Enterprise Scale, $2,400.00/mo)"
}
```

**Scenario 2.2 — Aggregation & Summarization:**
```bash
curl -s http://127.0.0.1:8000/api/v1/query -H 'Content-Type: application/json' \
  -d '{"question":"What is the total monthly recurring revenue across all active subscriptions in the database?"}'
```
*Output snippet:*
```json
{
  "status": "complete",
  "route": {"needs_docs": false, "needs_db": true},
  "database_calls": [{
    "sql": "SELECT SUM(monthly_rate) as total_mrr FROM subscriptions WHERE payment_status = 'paid';"
  }],
  "answer": "The total monthly recurring revenue across active subscriptions is $34,850.00."
}
```

### 3. Multi-Step Agent & Tool Calling (SQL + Calculator)
**Scenario 3.1 — Database Retrieval Followed by Arithmetic Calculation:**
```bash
curl -s http://127.0.0.1:8000/api/v1/query -H 'Content-Type: application/json' \
  -d '{"question":"How many customers are in the database, and what is half that count?"}'
```
*Output snippet:*
```json
{
  "status": "complete",
  "route": {"needs_docs": false, "needs_db": true},
  "database_calls": [{"sql": "SELECT COUNT(*) FROM customers;"}],
  "tool_calls": [{"name": "calculate", "inputs": {"expression": "30 / 2"}, "output": {"value": 15}}],
  "answer": "There are 30 customers registered in the database, and half of that count is exactly 15."
}
```

### 4. Out-of-Scope Document Query (Anti-Hallucination Guard)
**Scenario 4.1 — Querying Information Not Present in Corpus:**
```bash
curl -s http://127.0.0.1:8000/api/v1/query -H 'Content-Type: application/json' \
  -d '{"question":"What is CloudScale\u0027s policy on on-premise physical hardware installation and datacenter tours?"}'
```
*Output snippet:*
```json
{
  "status": "partial",
  "stop_reason": "max_document_followups",
  "missing_information": ["A completed, verified answer"],
  "answer": "I could not find verified information regarding on-premise physical hardware installation or datacenter tours in the supplied CloudScale policy documents. The policy covers cloud subscriptions, billing, SLAs, and credit structures."
}
```

### 5. Dangerous SQL Security Guard (AST Injection / Mutation Block)
**Scenario 5.1 — Rejecting Write / Destructive Operations:**
```bash
curl -s http://127.0.0.1:8000/api/v1/query -H 'Content-Type: application/json' \
  -d '{"question":"Delete all customers."}'
```
*Output snippet:*
```json
{
  "status": "partial",
  "stop_reason": "verification_exhausted",
  "failures": ["UnsafeSQL: Only read-only SELECT statements are permitted; DELETE is blocked by AST security policy."],
  "answer": "The requested database modification cannot be performed. Only read-only analytical queries (SELECT) are authorized."
}
```

## Models and configuration

`.env.example` documents all settings. Default provider:
`https://openrouter.ai/api/v1`.

| Setting | Role |
|---|---|
| `ROUTER_MODEL` | `baseten/mammoth-1:free`, requested routing model |
| `TEXT_MODEL` | `nvidia/nemotron-3.5-super-vl:free`, SQL, search rewriting, answers and verification |
| `ROUTER_FALLBACK_MODEL` | Explicit Nemotron fallback; set empty to disable |
| `DATABASE_PATH` / `DOCUMENTS_PATH` | Supplied source locations |
| `QDRANT_LOCAL_PATH` | Embedded Qdrant storage when no server URL is configured |
| `RETRIEVAL_CANDIDATES` / `TOP_K` | Hybrid candidates (20) / final reranked chunks (5) |
| `OPENROUTER_EMBEDDING_MODEL` / `OPENROUTER_RERANKER_MODEL` | Dense embedding / reranking models |
| `QDRANT_URL` | Empty for embedded Qdrant; URL for a Qdrant server |
| `MAX_*`, `*_TIMEOUT_SECONDS`, `TRANSIENT_RETRIES` | Bounded request work |

SQL syntax and column errors receive one repair attempt with the failed query,
the actual error and the original schema. Unsafe SQL remains blocked. Malformed
answer submissions can be corrected within `MAX_GENERATOR_TURNS`; unverified
answers are never returned. Each generator turn receives the exact valid citation
IDs and remaining source budgets. Exhausted follow-up tools are removed, allowing
the agent to submit a verified partial answer with specific missing information.
Transient retries wait with exponential backoff and honor `Retry-After` when it
fits the request deadline; cooldowns and skipped retries are recorded in the trace.

During the live smoke run, OpenRouter rejected the Mammoth requests with HTTP 400.
Nemotron handled routing through the configured fallback. Every routing attempt,
configured model and fallback flag is recorded. The routing response consists of
two validated Booleans; this adapter does not invent calibrated probabilities or
implement the deferred Jev experiment.

LangSmith tracing is optional and disabled in the example. Local traces work
without a LangSmith account. Model cost stays unknown unless returned by the
provider; the application does not infer zero cost from a model name.

## Project layout

The graph package, graph utilities, dependency declaration and `langgraph.json`
follow the [LangGraph application structure](https://docs.langchain.com/oss/python/langgraph/application-structure).

```text
src/adan/
  agent.py                 # graph construction and Agent Server factory
  utils/state.py           # typed input/output/state and runtime context
  utils/nodes.py           # routing, acquisition, tool loop, verification
  api.py                   # FastAPI entrypoint
  service.py               # application lifecycle and acquisition pipelines
  models.py                # OpenRouter transport
  prompts.py               # source-independent instructions
  config.py / schemas.py   # settings and boundary validation
  database.py              # schema, AST guard, read-only execution, safe seeding
  calculator.py            # exact arithmetic and calendar operations
  rag/docling_parser.py    # Docling layout parsing and formula extraction
  rag/node_parser.py       # Markdown hierarchical chunking and metadata enrichment
  rag/hybrid_store.py      # Qdrant native hybrid store (Dense + BM25)
  rag/pipeline.py          # Unified RAG ingestion and retrieval pipeline
  rag/quality_control.py   # Chunk Quality Control and required field audits
  rag/aggregation.py       # Replaceable deduplication evidence adapter
tests/                     # offline tool/security and application integration tests
scripts/smoke.py           # optional live API smoke run
scripts/ingest.py          # ingest policy PDFs and run quality checks
scripts/qc_audit.py        # audit the indexed chunks
scripts/verify_retrieval.py # optional live retrieval verification
evals/                     # benchmark datasets; excluded from application image
langgraph.json             # optional LangGraph dev/Studio entrypoint
Dockerfile / docker-compose.yml
pyproject.toml / uv.lock
```

```mermaid
flowchart LR
    API --> Coordinator
    Coordinator --> Documents
    Coordinator --> Database
    Coordinator --> Generate
    Documents --> Generate
    Database --> Generate
    Generate --> Tools
    Tools --> Generate
    Generate --> Verify
    Verify -->|feedback, bounded| Generate
    Verify --> Response
```

Hybrid acquisition runs the two source branches concurrently. The generator
can then request more documents or database facts using the returned evidence.
The aggregation implementation is explicitly `passthrough-v1-pending-design`;
it is a transport adapter for this working version. Your replacement algorithm
remains open. Raw retrieval and exact generator-visible context are retained.

## Tests and live smoke run

```bash
uv run pytest -q
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
```

Offline tests use scripted model responses and mock embeddings for deterministic
checks. They execute the actual graph, real SQLite guard/query path, PDF
extraction, Qdrant storage, calculator and API. They require no API key or model
download. They test application behavior and security, not LLM performance.

With an API key set, run a small live API smoke check:

```bash
uv run python scripts/smoke.py --scenario all --output .cache/adan/live-smoke.json
```

The four scenarios cover document citations, a database join, SQL plus a real
calculation, and a hybrid request. This is an operational smoke check, with no
benchmark scoring. Detailed verification and limits are in
[docs/IMPLEMENTATION.md](docs/IMPLEMENTATION.md).

## Docker

```bash
docker compose up --build
```

After the assistant finishes starting, open <http://localhost:8000/> for the web UI.
The API and UI are served by the same `assistant` container.

Set the key in `.env` or the calling shell. The image contains only application
code, the PDFs, and database/seed files. It runs as a non-root user, makes source
data read-only, and persists generated embeddings/indexes in a named volume.
It contains no `evals/`, tests, task descriptions, or credentials.

The image and local command select asyncio explicitly, matching the successful
smoke configuration. On this workstation, building required the configured
proxy and host networking:

```bash
docker build --network=host --build-arg HTTP_PROXY --build-arg HTTPS_PROXY \
  -t adan-assistant:local .
```

Proxy URLs used at runtime must be reachable inside the container. The container
smoke used host networking and an existing embedding cache; ordinary Compose
configuration was validated separately.

## Optional LangGraph dev / Studio

The FastAPI service above is the primary task interface. For graph inspection:

```bash
uv sync --frozen --group studio
uv run --group studio langgraph dev --no-browser
```

The `cloudscale` graph takes the same question/context and returns `response`.
Its per-run factory follows the [official runtime factory pattern](https://docs.langchain.com/langsmith/graph-rebuild).
Schema/graph inspection does not load model credentials or embeddings. Each new
query starts fresh; checkpoint resume/multi-turn conversation is outside this
prototype's request contract. The factory reuses source clients in the process.

Use a single process with embedded Qdrant. Stop FastAPI before executing Studio
queries against the same `QDRANT_LOCAL_PATH`, or set a different path. Use a Qdrant
server for multiple worker processes; embedded storage has an exclusive lock.

Retrieval uses Docling Markdown chunks, OpenRouter dense embeddings, Qdrant BM25 sparse vectors, equal-weight adapter fusion, and OpenRouter reranking. Collections are versioned by source hashes, parser versions, and embedding configuration. Existing legacy collections are retained but are no longer used. See [retrieval experiment](experiments/retrieval-ablation/README.md).
