# Evaluate a saved API response

`POST /api/v1/query` returns a versioned end-to-end run record. `Assistant.ask`
returns the same dictionary; the LangGraph Agent Server wraps it in `response`.
Existing response fields are retained. The API explorer at `/docs` describes
the response schema, including typed `timings` and `usage` objects.

Send only a benchmark case's `question` and complete `input_context`. Keep
`question_id`, expected answers, source flags, reference SQL/rows, and judge
rubrics in your evaluator. The application does not load the benchmark or use
its expected route. Attach `question_id` to the saved record outside the API.

| Response field | Evaluation use |
|---|---|
| `schema_version`, `mode`, `run_id`, `question`, `input_context` | Identify the contract (`1.0`), execution mode (`end_to_end`), run, and actual visible inputs. |
| `answer`, `status`, `stop_reason`, `missing_information` | Answer correctness, completeness, uncertainty, and completion statistics. |
| `retrieved_document_chunks` | Raw cumulative document ranking before aggregation, for evidence recall and context precision. |
| `retrieval_calls` | Every search attempt with query, ranked output, status, dispatch sequence, and timing; distinguishes failed searches from successful empty results. |
| `database_results` | Successful live SQL results, including SQL, parameters, columns, rows, and truncation flags. Compare to expected rows using equivalent projections and unordered multisets where appropriate. |
| `database_calls` | Every SQL execution attempt, including blocked and failed calls. |
| `aggregation_artifacts` | Each aggregator's `input_chunks`, output `chunks`, and version. Raw retrieval and supplied generator evidence may differ. |
| `generator_contexts` | Exact visible messages for each generator turn, including evidence and prior tool messages; the faithfulness boundary. |
| `calculator_trace` | Actual calculator execution attempts with arguments, outputs, status, and timing. Empty means no calculator ran; a failed attempt is not a successful calculation. |
| `citations` | Final cited chunk IDs, source metadata, and passage text; independently resolve source locations for citation checks. |
| `route`, `tool_calls`, `guardrail_history`, `execution_trace`, `failures` | Actual routing, tool execution, verification/revisions, and failures. |
| `timings` | UTC start/finish timestamps and total elapsed `duration_ms`, measured with a monotonic clock. Do not sum concurrent step durations for run latency. |
| `usage` | Model/tool attempt counts, generator turns, and reported model token/cost totals. Retries and routing fallbacks count as attempts. |
| `effective_limits`, `index_fingerprint` | JSON-safe settings/model configuration with provider and Qdrant keys omitted, plus the active index version. |

`retrieved_document_chunks` orders successful search calls by
`dispatch_sequence`, preserves each call's ranking, and deduplicates by
`chunk_id` on first occurrence. It retains every returned chunk, including
those dropped before or during aggregation. Use its first `k` items for
cumulative recall/precision at `k = 5, 10, 20`; the original per-call lists stay
in `retrieval_calls`. Similarity scores are not compared across queries.

An empty evidence list is a recorded absence; the associated call histories
and `failures` explain acquisition errors. Interrupted runs retain acquired
evidence and return a qualified answer with an explicit stop reason. A valid
HTTP 200 can therefore describe a partial or unsuccessful run.

`usage.input_tokens`, `output_tokens`, `total_tokens`, and `cost` are totals for
the traced chat model calls only. Each total is `null` if any attempt lacks
that value, including failed requests whose usage is unknown. A reported zero
cost stays zero. Per-attempt values remain in `execution_trace`. Embedding and
reranker provider costs are not captured here, so this is not total pipeline
billing. No cost is estimated from model names. Token counts use LangChain's
[reported message usage](https://docs.langchain.com/oss/python/langchain/messages#token-usage).

For the RAG benchmark's judges, the response directly supplies `answer`,
`question`, `input_context`, `missing_information`, `citations`,
`generator_contexts`, `retrieved_document_chunks`, `database_results`, and
`calculator_trace`. Join reference-only judge inputs from the matching benchmark
record in the evaluator. Resolve `cited_source_passages` independently from
the frozen source files rather than treating generated citation text as a
verified reference. Never treat uncaptured or failed calculator calls as proof
of numerical correctness.

For example, collect one case against a running API using the standard library:

```python
import json
from pathlib import Path
from urllib.request import Request, urlopen

case = json.loads(Path("evals/rag/benchmark.jsonl").read_text().splitlines()[0])
payload = {key: case[key] for key in ("question", "input_context")}
request = Request(
    "http://127.0.0.1:8000/api/v1/query",
    data=json.dumps(payload).encode(),
    headers={"Content-Type": "application/json"},
)
with urlopen(request, timeout=180) as response:
    output = json.load(response)
record = {"question_id": case["question_id"], **output}
Path("run.json").write_text(json.dumps(record, ensure_ascii=False, indent=2))
```

This collects an ordinary end-to-end run. Scoring, LLM judging, reference-source
resolution, and the separate `retrieval`/`generation` execution modes remain
external work described in [the evaluation contract](EVALUATION.md). This
response refactor does not implement those isolated modes or claim benchmark
scores.
