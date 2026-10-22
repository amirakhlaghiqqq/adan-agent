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
| **Phase 7** | Verification & Test Scenarios | `[ ] Not Started` | 5 core scenarios + 2 edge/security test cases |
| **Phase 8** | Dockerization & Reproducibility | `[ ] Not Started` | Dockerfile, docker-compose.yml (1-command run) |
| **Phase 9** | Documentation & Final Submission | `[ ] Not Started` | README.md, architecture doc, GitHub repo |

---

## Phase 1: Foundation & Environment Setup
- [x] Initialize Git repository (`git init`).
- [ ] Create project folder structure (`src/`, `data/`, `tests/`, `docs/`).
- [ ] Define dependencies in `requirements.txt` or `pyproject.toml`:
  - Web framework: `fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`
  - Agent / LLM framework: `langchain` / `langgraph` or clean modular OpenAI client
  - Vector Store & Embeddings: `chromadb` / `faiss-cpu`, `sentence-transformers` or OpenAI embeddings
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
  - *Document 1*: `sla_and_support_tier_policy.pdf` (LaTeX-compiled, 6 pages: Uptime targets, service credit matrices, Sev-1..Sev-3 SLA times).
  - *Document 2*: `enterprise_billing_and_refund_policy.pdf` (LaTeX-compiled, 4 pages: Net-30 invoicing, 14-day refund window, delinquency timeline).
- [ ] Implement **Meaningful PDF Preprocessor** (`src/rag/preprocessor.py`):
  - [ ] Extract raw text with page tracking.
  - [ ] Clean up noise (headers, footers, consecutive whitespaces, boilerplate).
  - [ ] Semantic chunking (chunk size ~400-800 tokens with overlap).
  - [ ] Attach structured metadata to each chunk (`source_file`, `page_number`, `section_title`).
- [ ] Ingest into Vector Store (`src/rag/vector_store.py`):
  - Automatic collection creation and embedding generation on startup/seeding.
- [ ] Implement RAG Sub-Agent (`src/agents/rag_agent.py`):
  - [ ] Top-$k$ semantic retrieval based on query embedding.
  - [ ] Grounded generation prompt: LLM answers using retrieved context.
  - [ ] **Citation Requirement**: Answer must explicitly cite the document name and page/section number.
  - [ ] **Strict Anti-Hallucination Guardrail**: If context does not contain the answer, return a clear declaration: *"The requested information is not available in the provided documents."*

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
- [ ] Implement **Deterministic Calculator Tool** (`src/tools/calculator.py`):
  - Real tool invoked via LLM Tool Calling (Function Calling).
  - Evaluates mathematical expressions safely (e.g., Python `numexpr` or AST-based math evaluation; avoids unsafe `eval()`).
  - Supports percentage calculations, differences, ratios, averages.
- [ ] Implement **Coordinator / Router Agent** (`src/agents/coordinator.py`):
  - [ ] Intent classification: analyzes user query and determines execution route:
    - Route A: Document search $\rightarrow$ delegate to `rag_agent`.
    - Route B: Database query $\rightarrow$ delegate to `sql_agent`.
    - Route C: Multi-step calculation $\rightarrow$ trigger hybrid flow.
- [ ] Implement **Multi-Step Hybrid Workflow**:
  - [ ] Step 1: Coordinator recognizes query requires tabular data + numerical computation.
  - [ ] Step 2: Calls `sql_agent` to fetch raw database metrics (e.g., sales total for Category A and Category B).
  - [ ] Step 3: Passes values to `calculator` tool (e.g., compute percentage difference: `(A - B) / B * 100`).
  - [ ] Step 4: Synthesizes final human-readable response.
- [ ] **Execution Tracing Requirement**:
  - Log/return the exact trace showing which agent(s) ran and which tools were invoked.

---

## Phase 6: FastAPI Backend & Quality of Implementation
- [ ] Build FastAPI server (`src/main.py`, `src/api/routes.py`):
  - Health check endpoint: `GET /health`
  - Unified query endpoint: `POST /api/v1/query` (takes prompt, returns answer + trace)
  - Dedicated sub-endpoints (optional/recommended): `POST /api/v1/rag`, `POST /api/v1/sql`
- [ ] Define Pydantic Schemas (`src/api/schemas.py`):
  - `QueryRequest`: `{ "prompt": str, "session_id": Optional[str] }`
  - `QueryResponse`:
    ```json
    {
      "answer": "string",
      "route_taken": "rag | sql | hybrid",
      "sub_agents_used": ["sql_agent", "calculator"],
      "sql_details": {
        "generated_sql": "SELECT ...",
        "raw_results": [...]
      },
      "sources": [
        { "document": "company_leave_policy.pdf", "page": 2, "section": "Sick Leave" }
      ],
      "execution_trace": [
        { "step": 1, "action": "sql_agent", "output": "..." },
        { "step": 2, "action": "calculator", "input": "...", "output": "..." }
      ]
    }
    ```
- [ ] Implement robust error handling middleware and exception handlers for:
  - Empty or malformed request payloads.
  - LLM API timeouts or rate limit errors.
  - Database execution exceptions.
  - Vector store connection issues.

---

## Phase 7: Verification & Test Scenarios

Verify the 7 mandatory scenarios explicitly required by the evaluation prompt:

- [ ] **Test Case 1: RAG Direct Retrieval**
  - *Query*: Specific factual question found in a single section of the PDF (e.g., *"How many days of annual leave are employees entitled to per year?"*).
  - *Verification*: Accurate answer + source document & page citation present.
- [ ] **Test Case 2: RAG Synthesized Retrieval**
  - *Query*: Question requiring synthesis across multiple chunks (e.g., *"Compare the rollover policy for unused annual leave versus sick leave."*).
  - *Verification*: Comprehensive synthesized response citing both relevant sections.
- [ ] **Test Case 3: RAG Ungrounded / Out-of-Scope (Anti-Hallucination)**
  - *Query*: Question on topic absent from documents (e.g., *"What is the company policy for employee gym membership reimbursements?"*).
  - *Verification*: Assistant explicitly declines and states information is not available; zero hallucinated facts.
- [ ] **Test Case 4: NL2SQL Filter + Aggregation**
  - *Query*: Numerical question with conditions (e.g., *"What is the total amount of completed orders in September 2024?"*).
  - *Verification*: Valid `SELECT SUM(amount) FROM orders WHERE status = 'completed' AND ...` generated, executed, and explained.
- [ ] **Test Case 5: NL2SQL Multi-Table Join**
  - *Query*: Question requiring relationship traversal (e.g., *"List all customers from Tehran along with the count of orders they have placed."*).
  - *Verification*: Valid `SELECT ... FROM customers JOIN orders ... GROUP BY ...` generated and executed correctly.
- [ ] **Test Case 6: NL2SQL Security & Dangerous Query Handling**
  - *Query*: Injection or mutating instruction (e.g., *"Delete all cancelled orders"* or `DROP TABLE customers;--`).
  - *Verification*: Guardrail intercepts query, execution blocked, safe error message returned, DB remains unchanged.
- [ ] **Test Case 7: Multi-Step Composite Scenario (SQL + Calculator Tool)**
  - *Query*: Question requiring DB extraction + arithmetic (e.g., *"What percentage of our total order revenue came from customers in Tehran?"*).
  - *Verification*: Logs show SQL sub-agent fetch totals $\rightarrow$ Calculator tool evaluates percentage $\rightarrow$ Final answer formulated.
- [ ] **Automated Tests**:
  - Implement `pytest` suite in `tests/` verifying routes, guardrails, calculator, and sub-agents.

---

## Phase 8: Dockerization & Reproducibility
- [ ] Write multi-stage or lightweight `Dockerfile`:
  - Python 3.11 / 3.12 slim base image.
  - Install dependencies cleanly with pinned versions.
  - Copy application code and seed data.
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
