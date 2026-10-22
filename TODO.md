# Project Master Checklist & Verification TODO

> **Project**: Multi-Agent Enterprise Assistant (Adan AI Hiring Task)  
> **Source Document**: [`adan-task (1).pdf`](file:///home/amir/Desktop/Projects/Adan/adan-task%20(1).pdf)  
> **Reference Spec**: [`TASK_SPECIFICATION.md`](file:///home/amir/Desktop/Projects/Adan/TASK_SPECIFICATION.md)  
> **Target Completion**: 24 Hours from receipt

---

## 📊 Progress Tracker

| Section | Milestone | Status | Critical Deliverables |
|:---:|:---|:---:|:---|
| **Phase 1** | Foundation & Environment | `[ ] Not Started` | Python venv, dependencies, `.env.example` |
| **Phase 2** | Relational Database & Seed Data | `[x] Data Ready` | $\ge 2$ related tables, seed script, `app.db` |
| **Phase 3** | Sample Documents & RAG Pipeline | `[x] PDFs Ready` | LaTeX PDFs generated & verified, ready for ingestion |
| **Phase 4** | NL2SQL Engine & Safety Guardrails | `[ ] Not Started` | Dynamic SQL gen, Join/Agg/Filter, Read-only guard |
| **Phase 5** | Coordinator Agent & Calculator Tool | `[ ] Not Started` | Router agent, tool-calling calculator, multi-step flow |
| **Phase 6** | FastAPI Backend & Error Handling | `[ ] Not Started` | REST API, input validation, execution traces |
| **Phase 7** | Capability Benchmark & Acceptance | `[x] Dataset / Modes Specified` | 48 cases; retrieval, generation, end-to-end runner pending |
| **Phase 8** | Dockerization & Reproducibility | `[ ] Not Started` | Dockerfile, docker-compose.yml (1-command run) |
| **Phase 9** | Documentation & Final Submission | `[ ] Not Started` | README.md, architecture doc, GitHub repo |

---

## Phase 1: Foundation & Environment Setup
- [x] Initialize Git repository (`git init`).
- [x] Create project folder structure (`src/`, `data/`, `tests/`, `docs/`).
- [x] Document System Architecture in `docs/ARCHITECTURE.md` (initial fan-out/fan-in, generator-owned follow-ups, replaceable aggregation, SQL guard, arithmetic/calendar tools).
- [ ] Define dependencies in `requirements.txt` or `pyproject.toml`:
  - Web framework: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`
  - Agent / LLM framework: `langchain` / `langgraph` or clean modular OpenAI client
  - RAG & Vector Store: `llama-index-core`, `llama-index-vector-stores-qdrant`, `qdrant-client`, `fastembed` / `sentence-transformers`
  - PDF & Data tools: `pypdf` / `pdfplumber`, `sqlite3` or `sqlalchemy`
  - Testing: `pytest`, `httpx`
- [ ] Create `.env.example` documenting all configuration keys:
  - `OPENAI_API_KEY` (or alternative LLM provider keys / base URLs)
  - `LLM_MODEL_NAME` (e.g. `gpt-4o-mini`, `gpt-4o`, `claude-3-5-sonnet`)
  - `EMBEDDING_MODEL_NAME`
  - `DB_PATH`
  - `SERVER_PORT` / `HOST`
- [ ] Implement central configuration loader in `src/config.py`.

---

## Phase 2: Relational Database & Seed Data
- [x] Design a clean, realistic schema with **at least 2 related tables** connected by foreign keys:
  - Table 1: `customers` (`customer_id`, `company_name`, `tier`, `region`, `contact_email`, `joined_date`, `status`)
  - Table 2: `subscriptions` (`subscription_id`, `customer_id`, `plan_name`, `billing_cycle`, `monthly_rate`, `start_date`, `renewal_date`, `payment_status`)
  - Table 3: `incident_tickets` (`ticket_id`, `customer_id`, `severity`, `downtime_minutes`, `reported_at`, `resolved_at`, `status`, `sla_breached`)
- [x] Write initialization/seeding script (`data/database/seed_db.py`, `schema.sql`, `seed_data.sql`):
  - Sample data includes 30 customers, 30 subscriptions, and 20 incident tickets.
- [ ] Implement database manager module (`src/database/connection.py`):
  - SQLite connection with read-only cursor support.
  - Schema introspection function (extracts table definitions and columns to build LLM context).
  - Safe query execution handler.

---

## Phase 3: Sample Documents & RAG Sub-Agent
- [x] Create/provide **at least 2 realistic, concise PDF documents** in `data/documents/`:
  - *Document 1*: `enterprise_billing_and_refund_policy.pdf` (4 rendered pages; DOC-BIL-2024-V3).
  - *Document 2*: `sla_and_support_tier_policy.pdf` (6 rendered pages; DOC-SLA-2024-V2).
- [ ] Implement **Meaningful PDF Preprocessor** (`src/rag/preprocessor.py`):
  - [ ] Extract raw text with page tracking.
  - [ ] Clean up noise (headers, footers, consecutive whitespaces, boilerplate).
  - [ ] Semantic chunking (chunk size ~400-800 tokens with overlap).
  - [ ] Attach structured metadata to each chunk (`source_file`, `page_number`, `section_title`).
- [ ] Ingest into Vector Store (`src/rag/vector_store.py`):
  - Automatic collection creation and embedding generation on startup/seeding.
- [ ] Implement RAG Sub-Agent (`src/agents/rag_agent.py`):
  - [ ] Top-$k$ semantic retrieval based on query embedding.
  - [ ] Expose source-tagged raw retrieval results and the aggregation artifact separately.
  - [ ] Keep the aggregation interface replaceable; its algorithm will be designed separately.
  - [ ] **Citation Requirement**: Answer must explicitly cite the document name and page/section number.
  - [ ] **Qualified-answer guardrail**: Answer supported parts, identify missing facts and conflicting clauses, and abstain fully only when no substantive answer is supported. Distinguish unavailable evidence from tool failure.

---

## Phase 4: NL-to-SQL Sub-Agent & Security Guardrails
- [ ] Implement NL2SQL Sub-Agent (`src/agents/sql_agent.py`):
  - [ ] Prompt injects database schema and column metadata.
  - [ ] Generates syntactically correct SQLite query without hardcoded mappings.
  - [ ] Natural language explanation of SQL results.
- [ ] Implement **Core Query Capabilities**:
  - [ ] **Filtering**: Handles `WHERE` conditions (e.g. date filters, category equals, status checks).
  - [ ] **Aggregation**: Handles `SUM`, `AVG`, `COUNT`, `MAX`, `MIN`, `GROUP BY`.
  - [ ] **Joins**: Successfully performs `INNER JOIN` / `LEFT JOIN` between related tables.
- [ ] Implement **Strict Security Guardrails** (`src/tools/sql_guard.py`):
  - [ ] **Read-Only Enforcement**: Verify query starts strictly with `SELECT`.
  - [ ] **Disallow Mutating Statements**: Block `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `CREATE`, `REPLACE`, `EXEC`.
  - [ ] **SQL Injection Defense**: Block semicolon chaining (multiple queries) or malicious SQL comments.
  - [ ] **Error Catching**: Catch SQL syntax errors, invalid column names, or execution timeouts and return structured, user-friendly error messages.
- [ ] **Transparency Requirement**:
  - Expose generated SQL query and raw execution output in the response payload or execution logs.

---

## Phase 5: Coordinator Agent & Calculator Tool
- [x] Complete [the Jev/model comparison task](to-do-tasks/evaluate-coordinator-models.md) using the balanced 64-case routing benchmark before selecting a coordinator backend (results and traces saved in `experiments/`).
- [ ] Implement **Deterministic Calculator Tool** (`src/tools/calculator.py`):
  - Real tool invoked via LLM Function Calling.
  - Allowlisted, bounded AST arithmetic without `eval()`, retaining exact values for bracket comparisons.
  - Typed `date_difference(start_date, end_date)` and `month_minutes(year, month)` operations using calendar dates and UTC month lengths.
  - Validate arguments and return structured values, units, and errors. Round only for final display.
- [ ] Implement **Coordinator / Router Agent** (`src/agents/coordinator.py`):
  - Independent `needs_docs` / `needs_db` flags for initial routing; propagate the question and complete `input_context`.
  - Run initial hybrid branches concurrently and join dispatched branches, including structured failures.
- [ ] Implement **Answer Generator Tool Loop**:
  - Inspect returned DB facts and document evidence; request a focused document or SQL follow-up when needed.
  - Resume after each tool result, including re-aggregation through the normal document path. No new dependency-planning node.
  - Invoke arithmetic/calendar operations for derived numerical results. Quoting supplied numerical facts requires no redundant calculation.
  - Enforce shared request/tool/turn/follow-up limits from [ARCHITECTURE.md](docs/ARCHITECTURE.md#44-bounded-follow-ups-and-stop-behavior); do not retry security blocks.
  - Return supported partial findings and an explicit stop reason when evidence or budget is insufficient.
- [ ] Implement **Reflective Output Guardrail & Verification Loop** (`src/agents/output_guard.py`):
  - Audit candidate responses against retrieved nodes, SQL results, and calculator outputs.
  - Verify citation validity, factual faithfulness, and calculation consistency.
  - Route back to Answer Generator with specific feedback on failure, bounded to max 2 retries.
  - Trigger polite, calibrated fallback response if verification fails after 2 attempts.
- [ ] **Execution Tracing Requirement**:
  - Append every retrieval round, SQL request/result, aggregation artifact, calculator call, failure, and generator-visible context.
  - Preserve call/parent IDs, dispatch order, arguments, outputs, timing, status, and effective limits without overwriting earlier calls.
  - Keep benchmark truth outside application prompts, indexes, caches, and agent-accessible files.

---

## Phase 6: FastAPI Backend & Quality of Implementation
- [ ] Build FastAPI server (`src/main.py`, `src/api/routes.py`):
  - Health check endpoint: `GET /health`
  - Unified query endpoint: `POST /api/v1/query` (takes prompt, returns answer + trace)
  - Dedicated sub-endpoints (optional/recommended): `POST /api/v1/rag`, `POST /api/v1/sql`
- [ ] Define Pydantic Schemas (`src/api/schemas.py`):
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
- [ ] Implement robust error handling middleware and exception handlers for:
  - Empty or malformed request payloads.
  - LLM API timeouts or rate limit errors.
  - Database execution exceptions.
  - Vector store connection issues.

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

The application and runner are still pending; no model-performance results are
claimed. Preserve the existing question banks and avoid benchmark-specific answers
in application prompts.

---

## Phase 8: Dockerization & Reproducibility
- [ ] Write multi-stage or lightweight `Dockerfile`:
  - Python 3.11 / 3.12 slim base image.
  - Install dependencies cleanly with pinned versions.
  - Copy application code and source data; keep benchmark answer keys and judge artifacts outside the agent-accessible application image.
- [ ] Write `docker-compose.yml`:
  - Port forwarding (e.g. `8000:8000`).
  - Environment variable passthrough via `.env`.
  - Automatic startup execution of DB seeding and PDF vector indexing.
- [ ] **One-Command Launch Test**:
  - Run `docker compose up --build`.
  - Verify app starts with no manual intervention and `/health` returns 200 OK.

---

## Phase 9: Documentation & Deliverables Checklist
- [ ] Write clean, comprehensive `README.md` containing:
  - [ ] **Project Overview**: Problem statement and architecture diagram.
  - [ ] **Setup & Quickstart**:
    - `.env` setup guide.
    - One-line Docker run command (`docker compose up --build`).
    - Local development instructions (without Docker).
  - [ ] **API Documentation**:
    - Endpoints specification.
    - Ready-to-run `curl` commands and expected JSON responses.
  - [ ] **Demonstration Scenarios**:
    - Logged outputs for all 7 required test cases.
  - [ ] **Design Decisions & Architecture**:
    - Reasons for chosen vector store, embedding model, routing mechanism.
    - SQL security mechanisms.
  - [ ] **Known Limitations & Future Improvements**:
    - Realistic discussion of production scaling, security hardening, etc.
- [ ] Final repository hygiene:
  - Ensure `.env` is in `.gitignore` (only `.env.example` committed).
  - Ensure no sensitive API keys are in git history.
  - Ensure code is formatted (PEP8 / `black` / `ruff`).
- [ ] Push to public or accessible GitHub repository for evaluation team.
