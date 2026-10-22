# Working application

This document describes the implemented prototype. The earlier architecture and
evaluation documents remain design inputs; their separate task lists and model
comparison work were not executed here.

## Evidence and safety

- PDF extraction uses `pdftotext -layout`. Repeated page furniture and standalone
  page numbers are removed; sections are chunked within rendered pages. Stable
  chunk IDs retain the source filename, document ID, page, section and passage.
- LlamaIndex uses local FastEmbed `all-MiniLM-L6-v2` embeddings and Qdrant cosine
  retrieval. Collections are keyed by source bytes, chunking version and embedding
  configuration. This prevents reusing an index after those inputs change.
- Aggregation is a replaceable temporary adapter. It passes tagged chunks
  through without implementing the proposed future aggregation algorithm.
- SQL is dynamically generated from inspected schema. SQLGlot restricts it to
  one SELECT; SQLite runs with `mode=ro`, `query_only`, a table/function authorizer,
  a progress deadline, and a 200-row output cap. Truncation is explicit. Security
  blocks are never retried. A missing database is seeded without replacing any
  existing database. The provided snapshot is preserved.
- The calculator interprets an allowlisted AST with exact fractions. It bounds
  expression length, node count, exponent, value magnitude and rational storage.
  Calendar operations use real calendar months and ISO dates. Money is displayed
  with Decimal `ROUND_HALF_UP`; comparisons retain the rational result.
- The generator receives user inputs, acquired evidence and actual tool results.
  It can request bounded document/SQL follow-ups. A separate model critic checks
  its submitted answer; unknown citation IDs are rejected deterministically.
  Rejected candidates get at most two correction cycles.
- Verification is model-assisted and can miss errors. It is not a formal proof
  of correctness. Missing information, failed acquisition and budget exhaustion
  remain distinct outcomes.
- Default limits are 120 seconds per request, 30 seconds per model attempt,
  20 seconds per tool attempt, 24 tool executions, 12 generator turns, two
  follow-ups per source and one transient retry per operation. Budget is reserved
  before tool execution. Every attempt retains its dispatch order, status and
  duration. Worker threads already doing local I/O cannot be forcibly killed;
  SQLite has its own shorter progress deadline.
- Runtime instructions contain no benchmark answers or fixed policy thresholds.
  Only the two named PDFs are indexed. No agent filesystem/shell tool is exposed.
  Credentials and hidden provider reasoning are excluded from application traces.

## Validation record

Tests were written before implementation, first observing missing modules or
failing behavior, then implementing until they passed. Commits separate the test
contracts, source tools, application, boundary fixes, and delivery setup.

The offline suite checks arithmetic/calendar boundaries, SQL mutation/injection
blocking, joins/aggregation, source preservation, PDF/index persistence, API
validation, graph execution, source follow-ups, parallel request isolation,
fallbacks, partial acquisition, request limits and correction exhaustion.
Embedding doubles validate storage/provenance, rather than semantic quality.

A live FastEmbed index was separately built from the PDFs and queried. Four
OpenRouter-backed FastAPI smoke requests completed with `stop_reason=completed`:

| Scenario | Observed behavior |
|---|---|
| Document | Payment-method answer with billing-policy page/section citations |
| Database | Generated customer/subscription join; three highest monthly rates |
| Calculation | Actual SQL count 30; actual calculator result 15 |
| Hybrid | Parallel policy and account acquisition; support tier, plan and cycle with citations |

The requested Mammoth ID received HTTP 400; the configured Nemotron fallback
provided the routing decisions. A transient HTTP 429 was retried within the
request budget. This establishes operation of these example paths, without
claiming benchmark accuracy, calibrated routing, latency or model comparisons.
Full local smoke traces are in ignored `.cache/adan/live-smoke.json`.

A separate real HTTP request on Uvicorn acquired both sources and called the
calendar/arithmetic tools (41,760 minutes; approximately 99.664751% uptime for the
explicit hypothetical inputs). Its final generation timed out and the retry
encountered a connection error. The API returned `partial`, retained its evidence
and reported `generation_error`; this additional request is not counted as a
successful final answer. Its trace is in `.cache/adan/final-socket-smoke.json`.

LangGraph dev served `/ok`, the assistant list, graph and schemas successfully.
Factory tests also exercise the graph with serializable inputs. Live model calls
through Studio were not needed for these checks; live requests used FastAPI.
The Docker image built successfully. Checks inside it confirmed UID 10001,
read-only source data, working SQLite/calculator operations, and absence of
`evals/` and `.env`. Compose configuration validation passed.

A real container HTTP request completed the SQL count and calculator workflow
using asyncio, the loop used by the successful smoke script. The shipped
Uvicorn command explicitly selects that loop. An earlier attempt using automatic
loop selection encountered model timeouts; this small smoke run does not prove
that event-loop selection caused those failures. Failed and successful traces
are kept separately in `.cache/adan/container-smoke.json` and
`.cache/adan/container-asyncio-smoke.json`.

Container verification used host networking, the workstation's existing proxy,
and a mounted embedding cache. The default Compose network was configuration-
checked, rather than used for the live provider request. The complete offline
suite passed **46 tests**, and Ruff lint/format checks passed.

## Scope left open

The replacement aggregation algorithm, Jev/model comparison, external retrieval/
generation/end-to-end benchmark runner, and LLM performance evaluation remain
separate work. The existing benchmark datasets stay under `evals/`.

The prototype has no authentication, tenancy authorization, streaming API or
durable replay of its in-memory acquisition state. It is intended for local task
demonstration with the supplied mock data. Use the primary FastAPI endpoint for
ordinary end-to-end requests.
