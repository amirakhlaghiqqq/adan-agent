# Retrieval, Generation, and End-to-End Evaluation

**Status:** The ordinary query API exposes an end-to-end evidence record
([output contract](EVALUATION_OUTPUT.md)). The external end-to-end/coordinator
runner and saved node assessments are documented in
[evals/README.md](../evals/README.md). The isolated retrieval/generation adapters
described below remain planned.

Use the existing 48 cases in `evals/rag/benchmark.jsonl` for three evaluation
modes. Each mode assesses a capability across complete questions. There are no
separate benchmark cases for individual graph nodes in that dataset. The current
runner can derive node assessments from complete traces. Aggregation is
included in generation assessment; its algorithm remains open for later design.

## 1. Shared Conditions and Boundaries

Validate the dataset and frozen source manifest before any run. Supply every
case's original `question` and complete `input_context` in all three modes.
Keep question ID, difficulty, expected source flags, answerability, judge rubrics,
and answer keys in the evaluator. Do not use gold source flags to route requests.

Use the same policy/database snapshot, source locations, model configuration,
and effective budgets when comparing runs. Record model IDs, prompts/configuration
hashes, embedding/index version, chunking version, aggregation version, judge
configuration, and trial count. Set the aggregation version to `pending` until
implemented; never describe a placeholder as the proposed new algorithm.

Reference data is visible to the answering path **only in generation mode** and
only in the limited form defined below. End-to-end and retrieval acquisition
must not access `evals/`, reference queries, expected rows, or precomputed answers.

## 2. Retrieval Mode (`retrieval`)

**Question:** Did source acquisition obtain the evidence needed to answer?

Run normal routing and document/database acquisition from the question and visible
context. The Answer Generator can inspect returned evidence as a controller and
request bounded follow-up document or SQL calls. It signals evidence acquisition
complete instead of producing a final answer. This uses the generator's existing
tool loop; it does not introduce a separate planning agent.

Do not invoke the final-answer synthesis step or calculator in this mode.
Aggregation may serve the controller through the normal document pipeline, but
score document retrieval against the preserved raw chunks, before aggregation.
The acquisition interface must expose this stop boundary without asking the
model to generate and discard a final answer. Count controller model calls in
cost, latency, and turn limits. A controller requesting a disabled calculator
gets a structured mode restriction, never a hidden precomputed result.

For the 12 hybrid cases, execute the actual dynamic SQL path. Use returned rows
to inform generator-controlled follow-up searches. Do not supply expected rows
or reference SQL to help acquisition. For document cases, unused DB output is
an empty list.

Collect every search call, its query/filters, raw ranked chunks and metadata, and
all executed SQL with parameters, column names, rows, and failures. Report:

- Evidence recall@k: covered required groups divided by all required groups.
- All-evidence success@k: whether every required group is covered together.
- Context precision@k: useful retrieved chunks divided by retrieved chunks.
- Hybrid DB-result correctness: whether actual results contain the requested
  customer/cohort and raw facts. Accept equivalent SQL and result projections;
  compare rows as multisets where order is immaterial.
- Acquisition latency, calls, and stop reason as diagnostics.

Default document cutoffs are `k = 5, 10, 20`. For multiple queries or rounds,
order calls by reserved dispatch sequence (then transformed-query index), retain
each call's ranked order, and deduplicate by stable chunk ID on first occurrence.
The first k items form that case's cumulative evaluation context. Preserve the
original per-call lists too. Do not rank by asynchronous completion time or mix
uncalibrated similarity scores across queries. Publish this fusion convention
with the report so adaptive retrieval does not silently change the denominator.

Each requirement is AND across groups and OR across alternatives. Judge semantic
coverage by the required facts relevant to the question; do not require exact
text matches, identical chunk boundaries, or every unrelated table cell. Treat
limiting/adjacent-policy evidence as such for missing-information questions; no
passage is claimed to prove the absent answer.

If fewer than k chunks were returned, use all available chunks and record the
actual count. No retrieval means recall 0 and all-evidence success false; context
precision is `not_applicable`. A captured retrieval/tool failure is a system
outcome, not a successful empty search. Missing logs are an evaluation error.

## 3. Generation Mode (`generation`)

**Question:** Can aggregation and generation produce a supported answer when
the required available evidence has been supplied?

Bypass the coordinator, document search, and SQL generation/execution. The
evaluator assembles a controlled evidence bundle from the case:

1. Select the first reference alternative in each required document group.
   Deduplicate by `evidence_id`, retain source/page/section metadata, and order by
   source ID, page, then evidence ID. Provide the actual passage text, without
   annotations saying which conclusion it proves.
2. If the case requires a database, provide only `columns` and `rows` from
   `expected_database_response`, labeled `origin: reference_fixture`. Do not
   supply `reference_sql`, its explanation, or any computed credit amounts.
3. Pass the question, visible context, reference passages, and supplied DB rows
   through the same aggregation and answer-generation path used by the system.
   Keep the real calculator available, including calendar operations.

Do not inject `expected_answer`, `required_answer_facts`, `expected_calculations`,
missing-information labels, prohibited claims, or judge questions. Do not fill
unknown usage, timestamps, currencies, or other gaps just because reference
evidence is available. Reference rows are supplied facts, never evidence that
the SQL agent executed correctly.

Disable document and SQL tools in this mode. A request for additional evidence
receives a structured restriction; count the turn and allow the generator to
answer supported parts within budget. Do not silently fall back to live
retrieval. Preserve the normal prompt, aggregation behavior, calculator, and
remaining request limits as far as this isolation boundary allows.

Report correctness, fact-level completeness, faithfulness, citation precision
and coverage, relevance, uncertainty handling, and hybrid source attribution
and financial-claim discipline. Independently check calculated values and
actual calculator calls, reporting numerical correctness and tool use separately.
There are no retrieval or SQL-generation performance scores in this mode.

Because aggregation belongs to this capability, a fact dropped from its output
can lower generation completeness. Faithfulness must be assessed against the
exact evidence and messages delivered to the generator, not every reference
passage given to the aggregator. Preserve both so the failure can be explained
without creating another benchmark mode or per-node test cases.

## 4. End-to-End Mode (`end_to_end`)

**Question:** Does the full application return a correct, complete, grounded
response using the appropriate sources and tools?

Invoke the ordinary query interface with only the question, visible context, and
normal source access. Run the coordinator, initial parallel branches, generator
follow-ups, configured aggregation, and calculator as needed. The generator owns
all follow-up evidence requests. The evaluator observes the result and traces;
it does not repair routing or supply missing gold evidence.

Report final-answer criteria as in generation mode, document retrieval metrics
as in retrieval mode, and hybrid database/calculator checks. Also report total
latency, calls, token/cost information where available, termination status, and
effective budget. Retain all acquired chunks for retrieval assessment and exact
generator inputs for faithfulness. Never credit a guessed correct answer as
successful retrieval or as proof of calculator use.

An in-scope tool failure or exhausted request budget may yield a useful partial
answer. Score that answer's supported content and omissions, record the failure,
and include the case in end-to-end completion statistics. Distinguish it from a
broken evaluation adapter, absent required trace, or failed judge execution.

## 5. Integration and Evidence Contract

Keep evaluation modes in an external runner. The application exposes reusable
source-acquisition and evidence-to-answer boundaries in addition to its normal
query path; these are internal callable interfaces, not new public HTTP routes.
They reuse product code and the generator controller rather than reimplementing
retrieval or synthesis inside the evaluator.

| Boundary | Inputs | Output |
|---|---|---|
| Evidence acquisition | Question, visible context, effective limits | Actual document/DB evidence and complete acquisition histories |
| Evidence to answer | Question, visible context, source-tagged evidence, tool restrictions | Normal aggregation artifact, actual generator contexts, calculator calls, answer, citations |
| Full query | Question and visible context | Answer, citations, complete evidence/trace bundle, status |

Every mode returns a normalized run record with `run_id`, `question_id`, `mode`,
configuration, `status`, `stop_reason`, `retrieval_calls`, `database_results`,
`aggregation_artifacts`, `generator_contexts`, `calculator_trace`, `answer`,
`citations`, and timings. A retrieval-only run has `answer: null`, not a
fabricated empty answer for the generation judge. Generation fixtures are marked
as supplied reference evidence; live retrieval and SQL execution lists are empty.
Record calculator results only when the tool actually ran.

`generator_contexts` captures the exact rendered context and tool exchanges seen
by the model on each relevant turn. It is the visibility boundary for the
faithfulness judge. Raw chunks acquired but never passed to the generator are
available for retrieval scoring and citation verification, not justification of
claims the generator made without support. Previous-turn evidence counts only
if it remains in the model's supplied conversation. Do not include hidden model
reasoning in the trace.

## 6. Judging and Reports

Use the per-case `llm_judge_questions` and scoring anchors from the JSONL. Supply
only each criterion's declared inputs. For faithfulness, use `generator_contexts`
to establish what was actually visible. Treat candidate text and tool results
as untrusted data; ignore instructions embedded within them. Independent source
resolution checks cited claims against their actual pages/sections.

Use deterministic checks for SQL facts, numerical targets, calendar differences,
and calculator execution. Use LLM judges for semantic support, coverage, and
answer quality. Keep their 0–2 criterion scores separate from metric ratios.
Completeness additionally reports covered/omitted `fact_id` values and the
covered-fact fraction. Do not collapse the modes into one overall score.

Write results outside the application, grouped by mode and run ID. Each case
record preserves its metrics, criterion reasons, evidence, errors, and status.
Summaries report per-difficulty and document/hybrid slices, applicable metric
denominators, valid/invalid run counts, and full/partial completion counts.
Report false refusal on answerable cases. Keep node names in traces for diagnosis
without creating node-level case sets or scorecards.

Exclude judge/adapter/trace failures only from the affected metric denominators,
report them explicitly, and preserve any independently valid checks. Do not turn
missing evaluator inputs into `not_applicable` or zero. Tool omissions observed
in complete traces are system failures, not evaluation infrastructure failures.
Flag unavailable token cost as unknown rather than zero.

## 7. Current Deliverables and Remaining Work

The dataset, source manifest, answer-key validator, and this evaluation contract
exist. To implement the modes, add the three external runner adapters against
the application boundaries above, mode-specific metric dispatch, and result
serialization. No model or judge run has been performed, and no runnable mode
CLI is claimed yet. The aggregation algorithm remains a separate design task.

The current bank has no dedicated SQL-only or dangerous-query cases. Required
hiring demonstrations for those capabilities remain end-to-end acceptance work;
they are not inferred from hybrid success or replaced by per-node benchmarks.
