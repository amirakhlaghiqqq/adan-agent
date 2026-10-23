# Compose agent evaluation

Assessed **12 questions**. See [node_assessments.csv](node_assessments.csv) for one row per question and [summary.json](summary.json) for counts/denominators.

| Node diagnostic | Mean (0–1) | Scored questions | Unscored reasons |
|---|---:|---:|---|
| coordinator_score | 0.917 | 12 | {} |
| documents_score | 0.825 | 8 | {'NO_REFERENCE': 4} |
| database_score | 0.625 | 4 | {'NOT_APPLICABLE': 4, 'NO_REFERENCE': 4} |
| aggregation_score | 1.000 | 8 | {'NO_REFERENCE': 4} |
| generate_score | 0.375 | 8 | {'NO_REFERENCE': 4} |
| tools_score | 0.750 | 2 | {'NOT_APPLICABLE': 4, 'NOT_RUN': 2, 'NO_REFERENCE': 4} |
| guard_score | 0.750 | 4 | {'NOT_RUN': 4, 'NO_REFERENCE': 4} |
| finalize_score | 1.000 | 12 | {} |

## What the scores mean

- **Coordinator:** exact match against the benchmark's expected source flags.
- **Documents:** cumulative required-evidence recall@20 using existing reviewed chunk annotations, checked against the active corpus. Includes follow-up searches.
- **Database:** external semantic judge of requested raw DB facts versus reference rows; equivalent SQL/projections/order are accepted (0, 0.5, 1).
- **Aggregation:** fraction of acquired required evidence groups still present in aggregation outputs, using annotated stable chunk IDs. Current aggregation is a passthrough; this is retention, not a new algorithm benchmark.
- **Generate:** benchmark correctness rubric score divided by two. Completeness, faithfulness, citations, relevance and uncertainty remain separate judge columns (0–2).
- **Tools:** independently recomputed calculator execution accuracy. Required calculator omission scores zero if the generator finished; blocked/unreached tools are NOT_RUN. Reference numeric-value coverage is a separate diagnostic: presence of a number alone does not prove its meaning or the correct formula.
- **Guard:** agreement with deterministic citation-ID validation, then a separate Luna judge using each candidate's own visible context. Unknown IDs require rejection even if Luna finds the prose supported. Original Luna judgments are preserved.
- **Finalize:** JSON contract, input identity, finished traces, and faithful return of the verified candidate (or an explicit qualified result after interruption). A score of one here does not mean the answer is correct.

NO_REFERENCE means the dataset supplies no expected result for that node. The four routing-only cases therefore do not get invented answer/SQL scores. NOT_APPLICABLE means no required operation/evidence to score. NOT_RUN means the node was not reached. INFRASTRUCTURE_ERROR excludes affected node scores from means; EVALUATION_ERROR means collection/judge evidence was invalid. Observed pre-exclusion scores and detailed reasons remain in assessments/.

## Evidence and limits

- [selection.json](selection.json) records the coverage-based 12-case selection and reused responses. It is a purposive diagnostic sample, not an unbiased estimate of performance across all 112 cases. Selection occurred after collection began.
- runs/{suite}/{question_id}.json preserves each exact request, full API response and trace. assessments/ stores checks and reasons; judges/ stores judge requests, responses, model IDs, usage and failed attempts, without authentication headers.
- Expected answers/rows/rubrics stay outside the agent. The Compose image was checked to exclude evals, and its PDFs/database match the benchmark source hashes.
- Citation checks use actual PDF pages resolved independently with pdftotext. Faithfulness/guard judging is separate from answer-key-based judging, using exact generator visibility and no hidden answer key.
- Final LLM judgments use **Luna subagents (gpt-6-luna)**, as requested. All three available workers were dispatched in parallel with 26 schema-constrained assessment jobs. luna_jobs/ records their inputs; luna_results/ records their actual judgments; luna_judges/ links validated results to input hashes. Earlier Nemotron and Antigravity attempts are audit-only and excluded from the final CSV. Antigravity reached its account quota before the user requested Luna. Judgments remain uncalibrated model assessments, not objective truth.
- Saved runs contain **12 HTTP 429 attempts**, including recovered retries; **12 runs** used the configured routing fallback. The primary Mammoth chat requests returned HTTP 400; these are fallback-system results, not proof of primary-router quality.
- All agent models remain free OpenRouter endpoints; no paid OpenRouter endpoint was used. Final judgments use the requested Luna subagents. Unknown token/cost totals remain null, including failed attempts without provider usage. No inferred total cost is reported.
- Node diagnostics describe behavior inside an end-to-end run. They are not causally isolated node experiments; upstream mistakes can affect downstream outputs. No single blended overall score is produced.
- Final-answer faithfulness uses the exact final generator input, which retains the supplied conversation and current evidence. Each guard candidate is judged separately against its own exact input to avoid crediting later evidence. All original turns remain in the saved agent responses.

The original broader collection is retained separately at ../2026-10-23-compose/ after the user reduced the scope to 12 questions. It is excluded from this CSV and its denominators.
