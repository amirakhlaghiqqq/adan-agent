# Project requirement audit

Reviewed on 2026-10-23 against the five-page Persian project brief, before removing
the task PDF at the owner's request. The original PDF's SHA-256 is
`fa68e7badbdcf563be3c38982f301551e505ad0beb9132b499ae6ae2add088d9`;
its previous revision remains in Git history.

The table covers the implementation and delivery requirements from sections
3–8. A working prototype is the brief's acceptance threshold; production
authentication, CI/CD, GPU deployment and a GUI are not mandatory.

| Requirement | Implementation and verification evidence |
|---|---|
| Several realistic sample PDFs | Two enterprise policy PDFs and editable sources in `data/documents/`. |
| Meaningful preprocessing | Docling layout parsing, removal of page furniture, heading normalization, table/formula preservation, page spans and chunk quality checks in `src/adan/rag/`. Cold Docker ingestion exercises the real PDFs. |
| Real embeddings and semantic retrieval | OpenRouter dense embeddings and BM25 sparse retrieval in Qdrant; versioned index provenance; saved live retrieval calls contain actual passages and scores. |
| LLM answers grounded in retrieved sources | Generator receives retrieved evidence; inline source references and citation records include document/page/section. Two live RAG demonstrations are saved. |
| Explicit missing-information behavior | Out-of-corpus demonstration declines unsupported policy claims. The output critic and citation guard can reject unsupported answers; acquisition failures remain distinct from proven absence. |
| Small relational database with related tables and sample data | Three linked tables: 30 customers, 30 subscriptions and 20 incident tickets. SQLite snapshot plus schema/seed SQL are supplied. Missing databases are seeded without replacing existing ones. |
| Actual LLM-generated SQL; filtering, aggregation and joins | `service.py` supplies inspected schema to the SQL model. Live join and active-customer aggregation questions return inspectable SQL and raw results. A deterministic repair rejects an unrequested monthly billing-cycle filter on `monthly_rate`. No question-to-SQL lookup table is used. |
| Inspectable generated SQL and results | `database_calls` and `database_results` preserve SQL, parameters, columns, rows, errors and truncation in each API response. |
| Read-only SQL; invalid/dangerous queries handled | SQLGlot AST guard, SQLite read-only URI, authorizer, function/table allowlists, timeout and row cap. Tests cover mutations, injection, forbidden functions, syntax/schema repair and preservation of the database. A live mutation request is also included. |
| Two specialized components and a coordinator | Independent document/database graph nodes call separate acquisition pipelines. Coordinator returns both source flags; hybrid requests fan out concurrently. |
| Real calculator through model tool calling | `calculate` performs allowlisted arithmetic using exact fractions and real calendar operations. Live SQL count → calculator division → answer retains the actual tool exchange. |
| A multistep scenario and visible component/tool execution | SQL + calculator and hybrid demonstrations; `execution_trace`, acquisition histories, `calculator_trace` and exact generator-visible contexts show executed components. |
| Lightweight question/answer API | FastAPI `POST /api/v1/query`, OpenAPI at `/docs`, and `GET /health`; Docker demonstrations use real HTTP requests. |
| Input validation and controlled LLM/retrieval/SQL errors | Pydantic limits, bounded retries/backoff, SQL repair, tool-argument feedback, shared deadline, explicit statuses and retained failure traces. Offline resilience tests exercise these paths. |
| Runnable Docker with reproducible dependencies/data/setup | Dockerfile, frozen `uv.lock`, CPU dependencies, pinned Qdrant image, supplied PDFs/database/seed files, optional proxy configuration and audited startup ingestion. |
| Readable separation of API, agent logic and tools | `api.py`, `agent.py`/`utils/`, `service.py`, `runtime.py`, `database.py`, `calculator.py` and `rag/`; current architecture is documented. |
| At least two RAG, two NL2SQL and one combined/tool example | Eight scenarios in `scripts/smoke.py`: two RAG, join, filtered aggregation, SQL + calculator, hybrid, out-of-corpus and mutation request. Full responses are committed. |
| Out-of-document and unsafe/invalid SQL examples; useful automated tests | Saved out-of-corpus/mutation responses, deterministic forced-unsafe-SQL tests, invalid SQL repair tests and the full offline suite. |
| Accessible GitHub repository with source, Docker and sample data | Public repository: <https://github.com/amirakhlaghiqqq/adan-agent>. Visibility was verified with GitHub before delivery. |
| Environment example; README setup/model configuration/examples/architecture/limits/test commands | `.env.example`, updated `README.md`, `docs/ARCHITECTURE.md`, `docs/IMPLEMENTATION.md` and this audit. Credentials are excluded from Git and the runtime image. |
| Example outputs for RAG, SQL and agent/tool workflow | Actual Docker responses and verification metadata in `experiments/task-verification/2026-10-23/`, linked from the README. |

## Validation record

- Offline suite: **109 passed**. One expected warning states that embedded Qdrant
  does not implement server payload indexes; Compose uses the Qdrant server.
- Ruff lint and formatting passed for the 47 application, test and script files.
- A repo-wide Ruff check also finds 185 existing lint issues in `evals/`; this
  evaluator debt is outside the application changes.
- Compose configuration and entrypoint shell syntax checks passed.
- Live Docker evidence and per-scenario outcomes are recorded in
  [the saved verification summary](../experiments/task-verification/2026-10-23/summary.json)
  and [full responses](../experiments/task-verification/2026-10-23/responses.json).

## Scope and qualifications

Only free model endpoints are used for the demonstration. No LLM judge or new
benchmark scoring is performed in this audit. The earlier Luna benchmark remains
separate and predates the recovery/prompt fixes. Free provider availability,
rate limits and model mistakes remain limitations; passing demonstrations is not
a guarantee for every possible question.

The audit fixed unsupported policy claims in prompt navigation hints, inaccurate
README examples and workstation-specific Docker proxy defaults. Live checks also
found and fixed unsupported currency labels and a spurious billing-cycle filter
that excluded annual subscriptions from an aggregate. Startup now reuses a matching
index and still audits its chunks. Required source PDFs and database data are
retained; only the original hiring brief is removed.

The original 24-hour submission deadline and future interview expectations
cannot be established from repository state. Public GitHub visibility is verified;
the receiving team's internal access policy is outside this application's control.

## Remaining live failure

Seven of eight saved demonstration checks pass. The final active-customer
aggregation returned 27937 instead of 31984 because the SQL model invented a
paid subscription-status filter and a positive-rate condition. The monthly-cycle
repair guard does not cover this different semantic error. Aggregation execution
and traces work, but this question remains incorrect; full behavioral acceptance
is therefore not established. See the saved response and summary for evidence.
