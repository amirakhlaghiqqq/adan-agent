# Project Master Checklist & Verification TODO

> **Project**: Multi-Agent Enterprise Assistant (Adan AI Hiring Task)  
> **Source Document**: [`adan-task (1).pdf`](file:///home/amir/Desktop/Projects/Adan/adan-task%20(1).pdf)  
> **Reference Spec**: [`TASK_SPECIFICATION.md`](file:///home/amir/Desktop/Projects/Adan/TASK_SPECIFICATION.md)  
> **Target Completion**: 24 Hours from receipt

---

## 📊 Progress Tracker

**Audited: October 23, 2026.** Checked against the current working tree, existing
tests, and saved experiment/smoke artifacts. `[x]` means implemented or supported
by the stated evidence; `[ ]` means incomplete, partial, or awaiting verification.
Passing offline tests does not establish live model accuracy. Paths below name
the actual implementation where it differs from the original suggested layout.

| Section | Milestone | Status | Critical Deliverables |
|:---:|:---|:---:|:---|
| **Phase 1** | Foundation & Environment | `[x] Implemented` | Python environment, locked dependencies, settings, `.env.example` |
| **Phase 2** | Relational Database & Seed Data | `[x] Implemented / tested` | Three related tables, safe seeding, read-only DB manager |
| **Phase 3** | Sample Documents & RAG Pipeline | `[ ] Mostly implemented` | Docling, hybrid Qdrant, reranking; original chunk sizing/overlap and current-pipeline validation remain |
| **Phase 4** | NL2SQL Engine & Safety Guardrails | `[x] Implemented / tested` | Dynamic SQL, filter/join/aggregation execution, AST and SQLite guards |
| **Phase 5** | Coordinator Agent & Calculator Tool | `[ ] Mostly implemented` | Graph, calculator, follow-ups, critic, traces; decision-endpoint integration and Jev-specific work remain |
| **Phase 6** | FastAPI Backend & Error Handling | `[x] Implemented / tested` | Health/query endpoints, schemas, bounded errors, qualified responses |
| **Phase 7** | Capability Benchmark & Acceptance | `[ ] Partial` | Dataset validated; retrieval diagnostics exist; three capability modes and seven demos incomplete |
| **Phase 8** | Dockerization & Reproducibility | `[ ] Launch verification pending` | Dockerfile/Compose/entrypoint exist; current Compose config validates |
| **Phase 9** | Documentation & Final Submission | `[ ] Partial` | README exists but is stale; lint/format, secret-history audit, GitHub delivery remain |

---

## Phase 1: Foundation & Environment Setup
- [x] Initialize Git repository (`git init`).
- [x] Create project folder structure (`src/`, `data/`, `tests/`, `docs/`).
- [x] Document System Architecture in `docs/ARCHITECTURE.md` (initial fan-out/fan-in, generator-owned follow-ups, replaceable aggregation, SQL guard, arithmetic/calendar tools).
- [x] Define dependencies in `requirements.txt` or `pyproject.toml`:
  - Web framework: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`
  - Agent / LLM framework: `langchain` / `langgraph` or clean modular OpenAI client
  - RAG & Vector Store: `llama-index-core`, `llama-index-vector-stores-qdrant`, `qdrant-client`, `fastembed` / `sentence-transformers`
  - PDF & Data tools: `pypdf` / `pdfplumber`, `sqlite3` or `sqlalchemy`
  - Testing: `pytest`, `httpx`
- [x] Create `.env.example` documenting implemented configuration keys:
  - `OPENAI_API_KEY` (or alternative LLM provider keys / base URLs)
  - `LLM_MODEL_NAME` (e.g. `gpt-4o-mini`, `gpt-4o`, `claude-3-5-sonnet`)
  - `EMBEDDING_MODEL_NAME`
  - `DB_PATH`
  - `SERVER_PORT` / `HOST`
- [x] Implement configuration loading in `src/adan/config.py` and `src/adan/rag/config.py`.

**Evidence:** `pyproject.toml`, `uv.lock`, `.venv`, `.env.example`, and both
configuration modules exist. The PDF implementation uses Docling; SQLite is in
the standard library. Actual environment names are `OPENROUTER_*`, `TEXT_MODEL`,
`ROUTER_MODEL`, and `DATABASE_PATH`; host/port are Uvicorn CLI options. RAG has a
separate loader: application final retrieval size uses `TOP_K`, while the RAG
CLI uses `RERANK_TOP_N`.

---

## Phase 2: Relational Database & Seed Data
- [x] Design a clean, realistic schema with **at least 2 related tables** connected by foreign keys:
  - Table 1: `customers` (`customer_id`, `company_name`, `tier`, `region`, `contact_email`, `joined_date`, `status`)
  - Table 2: `subscriptions` (`subscription_id`, `customer_id`, `plan_name`, `billing_cycle`, `monthly_rate`, `start_date`, `renewal_date`, `payment_status`)
  - Table 3: `incident_tickets` (`ticket_id`, `customer_id`, `severity`, `downtime_minutes`, `reported_at`, `resolved_at`, `status`, `sla_breached`)
- [x] Write initialization/seeding script (`data/database/seed_db.py`, `schema.sql`, `seed_data.sql`):
  - Sample data includes 30 customers, 30 subscriptions, and 20 incident tickets.
- [x] Implement database manager module (`src/adan/database.py`):
  - SQLite connection with read-only cursor support.
  - Schema introspection function (extracts table definitions and columns to build LLM context).
  - Safe query execution handler.

**Evidence:** `tests/unit/test_tools.py` covers joins, filtered counts, unsafe
queries, and safe startup seeding. The supplied database has 30 customers,
30 subscriptions, and 20 incident tickets; existing data is preserved.

---

## Phase 3: Sample Documents & RAG Sub-Agent
- [x] Create/provide **at least 2 realistic, concise PDF documents** in `data/documents/`:
  - *Document 1*: `enterprise_billing_and_refund_policy.pdf` (4 rendered pages; DOC-BIL-2024-V3).
  - *Document 2*: `sla_and_support_tier_policy.pdf` (6 rendered pages; DOC-SLA-2024-V2).
- [ ] Implement **Meaningful PDF Preprocessor** (partial; `src/adan/rag/docling_parser.py` and `node_parser.py`):
  - [x] Extract text with page tracking.
  - [x] Clean up noise (headers, footers, excessive blank lines, boilerplate).
  - [x] Attach structured metadata (`source_file`, mapped page numbers, `section`/`header_path`/`clause_title`).
- [x] Ingest into Vector Store (`src/adan/rag/hybrid_store.py` and `pipeline.py`):
  - Automatic collection creation and embedding generation on startup/seeding.
- [x] Implement RAG branch (`src/adan/service.py`, `utils/nodes.py`, and `rag/pipeline.py`):
  - [x] Top-$k$ semantic retrieval based on query embedding.
  - [x] Expose source-tagged raw retrieval results and the aggregation artifact separately.
  - [x] Keep the aggregation interface replaceable; its algorithm will be designed separately.
  - [x] **Citation Requirement**: Implement document/page/section citation instructions and citation-ID checks.
  - [x] **Qualified-answer guardrail**: Implement supported/partial/insufficient-evidence answers, missing-information reporting, critic checks, and distinct tool failures.

**Remaining:** Markdown heading chunking exists, but it does not enforce the
original 400–800-token size/overlap requirement. Keep this open until implemented
or deliberately revised. Aggregation is intentionally
`passthrough-v1-pending-design`, not the future aggregation algorithm.
- [ ] Validate the complete current Docling → hybrid Qdrant → reranker path and
  inspect citation provenance, tables, and formulas. Existing unit tests mock
  remote calls; `tests/integration/test_retrieval.py` exercises the legacy
  `PolicyIndex`, not the active pipeline. Saved retrieval judgments note that
  the SLA uptime formula was not decoded and credit-table layout was degraded.

---

## Phase 4: NL-to-SQL Sub-Agent & Security Guardrails
- [x] Implement NL2SQL branch (`src/adan/service.py:query_database` and `utils/nodes.py`):
  - [x] Prompt injects database schema and column metadata.
  - [x] Generate SQLite queries dynamically, with validation before execution and no hardcoded mappings.
  - [x] Natural language explanation of SQL results through the answer generator.
- [x] Implement **Core Query Capabilities**:
  - [x] **Filtering**: Supports `WHERE` conditions (e.g. date filters, category equals, status checks).
  - [x] **Aggregation**: Supports `SUM`, `AVG`, `COUNT`, `MAX`, `MIN`, `GROUP BY`.
  - [x] **Joins**: Supports `INNER JOIN` / `LEFT JOIN` between related tables.
- [x] Implement **Strict Security Guardrails** (`src/adan/database.py`):
  - [x] **Read-Only Enforcement**: Validate the SQL AST as one SELECT/set operation, including permitted SELECT CTEs; enforce SQLite read-only access.
  - [x] **Disallow Mutating Statements**: Block `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `REPLACE`, `EXEC`.
  - [x] **SQL Injection Defense**: Reject multiple statements and forbidden operations using AST checks and SQLite authorization; harmless SQL comments are not categorically forbidden.
  - [x] **Error Catching**: Catch SQL errors/timeouts and expose structured failures to the generator and trace.
- [x] **Transparency Requirement**:
  - Expose generated SQL query and raw execution output in the response payload or execution logs.

**Evidence:** `tests/unit/test_tools.py` and application integration tests pass.
These establish execution support and guard behavior, not live NL-to-SQL accuracy
for every listed operator. SQL syntax alone does not prove a read-only query;
the implementation also uses `mode=ro`, `query_only`, an authorizer, execution
deadlines, and a 200-row result cap.

---

## Phase 5: Coordinator Agent & Calculator Tool
- [x] Run the Mammoth/Elephant/Nemotron comparison on the balanced 64-case routing benchmark, with results and traces saved in `experiments/`.
- [ ] Complete the Jev/model comparison: the runner currently provides OpenRouter decisions/chat adapters, not a Jev/TypeSafe adapter; saved runs use one trial per case, so repeatability is not established.
- [x] Implement **Deterministic Calculator Tool** (`src/adan/calculator.py` and generator tool dispatch):
  - Real tool invoked via LLM Function Calling.
  - Allowlisted, bounded AST arithmetic without `eval()`, retaining exact values for bracket comparisons.
  - Typed `date_difference(start_date, end_date)` and `month_minutes(year, month)` operations using calendar dates and UTC month lengths.
  - Validate arguments and return structured values, units, and errors. Round only for final display.
- [x] Implement **Coordinator / Router Agent** (`src/adan/agent.py` and `utils/nodes.py`):
  - Independent `needs_docs` / `needs_db` flags for initial routing; propagate the question and complete `input_context`.
  - Run initial hybrid branches concurrently and join dispatched branches, including structured failures.
- [ ] Integrate the selected decision endpoint into the application: `models.py` still uses structured Chat Completions for routing, while the experiment uses `/api/alpha/decisions`. Preserve explicit fallback and validate the resulting application path.
- [x] Implement **Answer Generator Tool Loop**:
  - Inspect returned DB facts and document evidence; request a focused document or SQL follow-up when needed.
  - Resume after each tool result, including re-aggregation through the normal document path. No new dependency-planning node.
  - Invoke arithmetic/calendar operations for derived numerical results. Quoting supplied numerical facts requires no redundant calculation.
  - Enforce shared request/tool/turn/follow-up limits from [ARCHITECTURE.md](docs/ARCHITECTURE.md#44-bounded-follow-ups-and-stop-behavior); do not retry security blocks.
  - Return supported partial findings and an explicit stop reason when evidence or budget is insufficient.
- [x] Implement **Reflective Output Guardrail & Verification Loop** (`src/adan/utils/nodes.py:guard`):
  - Audit candidate responses against retrieved nodes, SQL results, and calculator outputs.
  - Verify citation validity, factual faithfulness, and calculation consistency.
  - Route back to Answer Generator with specific feedback on failure, bounded to max 2 retries.
  - Trigger polite, calibrated fallback response if verification fails after 2 attempts.
- [x] **Execution Tracing Requirement**:
  - Append every retrieval round, SQL request/result, aggregation artifact, calculator call, failure, and generator-visible context.
  - Preserve call/parent IDs, dispatch order, arguments, outputs, timing, status, and effective limits without overwriting earlier calls.
  - Keep benchmark truth outside application prompts, indexes, caches, and agent-accessible files.

**Evidence:** The application/resilience tests exercise SQL → calculator →
answer, hybrid follow-ups, explicit router fallback, citation correction,
verification exhaustion, limits, trace completion, and request isolation.
Critic approval remains model-assisted rather than a correctness guarantee.
On budget/error termination, the API retains evidence and a qualified fallback;
it does not return the unverified candidate as a supported final conclusion.

---

## Phase 6: FastAPI Backend & Quality of Implementation
- [x] Build FastAPI server (`src/adan/api.py`):
  - Health check endpoint: `GET /health`
  - Unified query endpoint: `POST /api/v1/query` (takes prompt, returns answer + trace)
  - Dedicated sub-endpoints (optional/recommended): `POST /api/v1/rag`, `POST /api/v1/sql`
- [x] Define Pydantic Schemas (`src/adan/schemas.py`):
  - `QueryRequest`: `prompt`, `input_context` (list of visible instructions/assumptions, default `[]`), and optional `session_id`.
  - `QueryResponse`:
    ```json
    {
      "answer": "string",
      "answer_status": "complete",
      "stop_reason": "completed",
      "route_taken": "hybrid",
      "sub_agents_used": [],
      "sources": [],
      "retrieval_calls": [],
      "database_results": [],
      "aggregation_artifacts": [],
      "generator_contexts": [],
      "calculator_trace": [],
      "execution_trace": [],
      "effective_limits": {},
      "total_duration_ms": 0
    }
    ```
  - Each history entry contains actual arguments/results and source metadata as defined in the architecture; the empty arrays above illustrate shape only.
- [x] Implement request validation and graph/service/tool error handling for:
  - Empty or malformed request payloads.
  - LLM API timeouts or rate limit errors.
  - Database execution exceptions.
  - Vector store connection issues.

**Actual contract:** The request uses `question`, not `prompt`; optional
`input_context` defaults to `[]`. The response uses `status`, Boolean `route`,
`citations`, `database_calls`, `tool_calls`, and per-event durations, rather than
every illustrative field name above. There is no session ID, durable multi-turn
state, or dedicated RAG/SQL endpoint; those endpoints were optional. Captured
request failures can return HTTP 200 with qualified status/stop reason. A source
initialization failure still prevents startup rather than reporting healthy.
`tests/integration/test_application.py` verifies health, validation, and queries.

---

## Phase 7: Capability Benchmark & End-to-End Acceptance

Evaluate complete questions at three capability boundaries. Do not create a
separate question bank or scorecard for every internal node.

- [x] Create the 48-case JSONL dataset with reference evidence, DB rows, calculations, and judge questions.
- [x] Validate the answer key locally, including corrupt-record self-checks; these are dataset checks, not model/node performance tests.
- [x] Specify `retrieval`, `generation`, and `end_to_end` modes in [EVALUATION.md](docs/EVALUATION.md).
- [ ] Expose reusable acquisition and evidence-to-answer boundaries in application code; reuse normal generator-owned follow-ups and aggregation.
- [ ] Implement external `retrieval` adapter: acquire actual documents/DB facts, permit bounded source follow-ups, stop before final answer, score evidence coverage and hybrid DB correctness.
- [ ] Implement external `generation` adapter: supply reference passages/rows, run normal aggregation/generation with the real calculator, disable live retrieval/SQL, and score the answer against controlled evidence.
- [ ] Implement external `end_to_end` adapter: provide only the question/context and normal source access, then assess the final response, evidence, tools, and termination.
- [ ] Apply deterministic DB/numeric checks and the case-specific LLM judge criteria; use exact generator-visible context for faithfulness.
- [ ] Save separate mode reports with per-difficulty/document/hybrid slices, explicit denominators, invalid-evaluation counts, costs where known, and stop reasons.
- [ ] Record the seven required hiring demonstration scenarios from `TASK_SPECIFICATION.md` through the complete application interface. The current bank lacks dedicated SQL-only and mutation/security cases, so do not claim those requirements are covered by hybrid results.

**Audit:** The application exists. Reusable `search_documents`, `query_database`,
and graph nodes are present, but controlled evidence injection and the three
complete evaluation adapters are not. `scripts/run_retrieval_ablation.py` and
`evals/rag/retrieval_{judgments,metrics}.py` provide document-retrieval diagnostics;
these do not implement the specified retrieval mode's SQL correctness and
generator-controlled follow-ups, generation mode, or end-to-end scoring.

`experiments/retrieval-ablation/summary.json` contains 48-case results for six
configurations, with `reranker_model: "none"`. Its decomposition queries are
source-informed diagnostics, not a demonstrated deployable planner. Do not
interpret these results as reranker or final-answer performance.

Saved `.cache/adan/live-smoke.json` has four completed scenarios (documents,
database join, calculation, hybrid), while `scripts/smoke.py` defines the same
four. These older artifacts do not cover all seven acceptance scenarios or
validate the current retrieval implementation. Preserve the existing question
banks and keep benchmark-specific answers outside application prompts.

---

## Phase 8: Dockerization & Reproducibility
- [x] Write multi-stage or lightweight `Dockerfile`:
  - Python 3.11 / 3.12 slim base image.
  - Install dependencies cleanly with pinned versions.
  - Copy application code and source data; keep benchmark answer keys and judge artifacts outside the agent-accessible application image.
- [x] Write `docker-compose.yml`:
  - Port forwarding (e.g. `8000:8000`).
  - Environment variable passthrough via `.env`.
  - Automatic startup execution of DB seeding and PDF vector indexing.
- [ ] **One-Command Launch Test**:
  - Run `docker compose up --build`.
  - Verify app starts with no manual intervention and `/health` returns 200 OK.

**Evidence:** The current image definition uses Python 3.12, a frozen `uv.lock`,
a non-root user, read-only source files, and an allowlisted build context.
Compose starts Qdrant and the assistant; `docker-entrypoint.sh` waits for Qdrant,
runs ingestion/QC, then starts FastAPI. Application startup safely seeds a missing
database. `docker compose config --quiet` passes. Existing container smoke
artifacts include a completed SQL/calculator request and a failed generation,
but predate the current container/retrieval changes. The current image build and
default-network one-command launch were not rerun in this audit.

---

## Phase 9: Documentation & Deliverables Checklist
- [ ] Write clean, comprehensive `README.md` containing:
  - [x] **Project Overview**: Problem statement and architecture diagram.
  - [ ] **Setup & Quickstart**:
    - `.env` setup guide.
    - One-line Docker run command (`docker compose up --build`).
    - Local development instructions (without Docker).
  - [ ] **API Documentation** (partial):
    - Endpoints specification.
    - Ready-to-run `curl` commands and expected JSON responses.
  - [ ] **Demonstration Scenarios**:
    - Logged outputs for all 7 required test cases.
  - [x] **Design Decisions & Architecture** (basic implementation/design notes exist):
    - Reasons for chosen vector store, embedding model, routing mechanism.
    - SQL security mechanisms.
  - [x] **Known Limitations & Future Improvements**:
    - Realistic discussion of production scaling, security hardening, etc.
- [ ] Final repository hygiene:
  - [x] Ensure `.env` is in `.gitignore` (only `.env.example` tracked).
  - [ ] Audit git history for sensitive API keys; not verified by this audit.
  - [ ] Ensure lint and formatting checks pass (currently failing; see below).
  - [ ] Review and commit the current modified/untracked implementation and retrieval files for delivery.
- [ ] Push to public or accessible GitHub repository for evaluation team.

**Documentation remaining:** Local/Docker commands and API examples exist, but
the README still describes local MiniLM/FastEmbed startup and an older text
model, while current startup uses OpenRouter embeddings, Docling, and server
Qdrant by default. Its retrieval-experiment README link points to a missing file.
The API section lists response fields but lacks a concrete response example.
`docs/IMPLEMENTATION.md` and the architecture also need
reconciliation with current implementation/experiment status. Keep Setup &
Quickstart open until those instructions are consistent and freshly verified.
A complete set of seven logged demos remains missing. No Git remote is
configured; no push was attempted.

## Audit checks and remaining priorities

Checks run on October 23, 2026:

| Check | Result |
|---|---|
| `.venv/bin/python -m pytest -q` | **61 passed**, one embedded-Qdrant warning |
| `.venv/bin/python evals/rag/validate_benchmark.py --self-check` | **48 records and 21 validator self-checks passed**, including frozen-source checks |
| `.venv/bin/python evals/coordinator/runner.py --self-check` | Passed evaluator self-checks |
| `docker compose config --quiet` | Passed configuration validation; not a build/launch test |
| `.venv/bin/ruff check src tests scripts --output-format concise` | **Failed: 51 issues**, all reported in `scripts/run_retrieval_ablation.py` |
| `.venv/bin/ruff format --check src tests scripts` | **Failed: three files** need formatting: `scripts/run_retrieval_ablation.py`, `src/adan/service.py`, `tests/unit/test_rag_pipeline.py` |

Priority order for remaining work:

1. Validate current ingestion/retrieval content and citations, including the
   missing formula/table fidelity; resolve the original chunking requirement.
2. Connect the selected decision endpoint to the application and verify routing.
   Resolve whether Jev-specific comparison work remains required; retain the
   recorded one-trial limit on current experiment conclusions.
3. Complete the three capability evaluation modes and record all seven hiring
   demonstration scenarios, with appropriate scores and failure reporting.
4. Build and launch the current default Compose configuration, then check health
   and representative requests.
5. Reconcile documentation, fix lint/format findings, audit secret history,
   commit reviewed files, and configure/push the submission repository.

This audit changes the checklist only. No live provider calls, container startup,
secret-history scan, code fixes, commits, or publication were performed.
