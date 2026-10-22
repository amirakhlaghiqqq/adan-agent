# Structured RAG benchmark

`benchmark.jsonl` contains **48 assessment cases**: 16 easy, 16 medium, and 16 hard.
There are 36 document cases and 12 hybrid cases. All hybrid cases require both PDFs
and SQLite retrieval; 7 also require a calculator. IDs and question wording match
the existing `questions.md` and `hybrid_questions.md` banks.

This is a dataset and local answer-key validator. It does not call an answering
system, execute an LLM judge, or produce model-performance scores. Difficulty is
provisional until calibrated with real runs.

## Evaluation modes

The architecture defines three external evaluation modes using these same cases:

| Mode | What runs | What is assessed |
|---|---|---|
| `retrieval` | Normal source acquisition, including hybrid SQL and generator-controlled follow-up searches; no final answer | Required document evidence and DB facts obtained |
| `generation` | Reference passages and DB rows supplied to the normal aggregation/generator path; real calculator, no live retrieval or SQL | Answer quality with controlled available evidence |
| `end_to_end` | Full ordinary application path with only question, visible context, and source access | Final response quality, actual evidence coverage, SQL facts, and tool use |

These are capability-level assessments, not per-node test sets. The aggregation
algorithm remains open; evaluation records its inputs and outputs without
prescribing its design. Generation assessment includes aggregation and synthesis.

See [the evaluation contract](../../docs/EVALUATION.md) for evidence injection,
retrieval cutoffs, scoring boundaries, and report requirements. Runner and
application implementations are pending; the validation commands below check
the dataset, not these modes' model performance.

## Files and validation

- `benchmark.jsonl`: UTF-8 JSON Lines, one complete case per line.
- `source_manifest.json`: source paths, versions, PDF page counts, database table
  counts, and SHA-256 hashes. Includes the PDFs, SQLite file, schema, seed SQL,
  and both original Markdown banks.
- `validate_benchmark.py`: standard-library validation, with read-only SQLite and
  PDF evidence checks. The only external executable is `pdftotext` (Poppler).
- This README: schema and evaluation conventions.

From the repository root, using Python 3.10 or later:

```bash
python3 evals/rag/validate_benchmark.py
python3 evals/rag/validate_benchmark.py --self-check
```

An alternate dataset can be checked against the same frozen sources:

```bash
python3 evals/rag/validate_benchmark.py --dataset /path/to/candidate.jsonl --self-check
```

The validator exits 0 on success and 1 on failure. Record errors identify the
question ID; JSON syntax errors identify the line. Source drift is a dataset-wide
failure identified by source ID. It checks question preservation, coverage,
field types, source flags, evidence, SQL results, calculations, and judge rubric
structure. The self-check exercises malformed/corrupt cases and an accepted
whitespace/SQL alternative in memory, without editing source files.

If a source hash changes, review and update affected evidence, rows, and expected
answers before deliberately updating the manifest. Hashes are a snapshot check,
not proof that the manually curated answer key is semantically correct.

## Record schema, version 1.0

All following fields occur in every record. JSON booleans are actual booleans;
unneeded database output is `null`, and unneeded lists are `[]`. Blank lines,
duplicate JSON keys, and non-finite JSON numbers are rejected.

| Field | Type and meaning |
|---|---|
| `schema_version` | String, `"1.0"`. |
| `question_id` | Stable bank ID, such as `E01`, `H11`, or `X-M01`. |
| `question` | Original question, unchanged. |
| `difficulty` | `easy`, `medium`, or `hard`. |
| `category` | `document` or `hybrid`. |
| `is_document_1_needed` | Boolean: billing/refund PDF required. |
| `is_document_2_needed` | Boolean: SLA/support PDF required. |
| `is_database_needed` | Boolean: database retrieval required. |
| `is_calculator_needed` | Boolean: required arithmetic, rather than numerical rule lookup. |
| `input_context` | List of visible instructions and exercise assumptions. |
| `required_document_evidence` | List of required evidence groups described below. |
| `expected_database_response` | Reference query/result object, or `null`. |
| `expected_calculations` | List of structured calculation targets, or `[]`. |
| `expected_answer` | Human-readable reference answer, including relevant bank tables and calculations. |
| `required_answer_facts` | Objects with `fact_id` and `fact`, used for fact-level completeness checks. |
| `answerability` | `answerable`, `partially_answerable`, or `not_answerable`. |
| `missing_information` | Case-specific information unavailable from the supplied sources. |
| `prohibited_claims` | Descriptions of errors the answer must avoid; evaluator metadata, not system instructions. |
| `llm_judge_questions` | Case-specific criterion objects described below. |

### Sources and evidence groups

The source mapping is fixed:

| Source ID | File | Policy version |
|---|---|---|
| `document_1` | `data/documents/enterprise_billing_and_refund_policy.pdf` | DOC-BIL-2024-V3, effective 2024-02-01, 4 rendered pages |
| `document_2` | `data/documents/sla_and_support_tier_policy.pdf` | DOC-SLA-2024-V2, effective 2024-01-15, 6 rendered pages |
| `database` | `data/database/app.db` | Supplied snapshot; 30 customers, 30 subscriptions, 20 tickets |

Each evidence group has:

- `requirement_id`: stable, case-specific ID, for example `H01-R01`.
- `role`: `supporting_policy` or `limiting_or_adjacent_policy`.
- `alternatives`: one or more independently sufficient reference passages for
  that requirement. Each has `evidence_id`, `source_id`, `document_id`, `path`,
  `page` (one-based rendered PDF page), `section`, and `text`.

**All groups are required; any alternative within a group is acceptable.**
Evidence IDs identify reusable source passages and retain identical content
where repeated across cases. Alternative passages are provided where useful,
such as equivalent Starter exclusions or billing contact listings.

Text comes from `pdftotext -layout`. Validation uses Unicode NFC normalization
and collapses whitespace runs to a single space. It preserves punctuation,
case, and PDF line-break hyphenation. A valid passage must occur on its cited
page; matching only a heading or page number is insufficient.

These are reference evidence spans, not a prescribed chunking implementation.
In a future evaluation, judge whether retrieved content supplies the relevant
facts for the question. Do not require retrieval of every incidental table row
in a reference passage, exact string matches, or identical chunk boundaries.
Relevant content may span multiple retrieved chunks.

For H06 and H09, adjacent passages explain the related policy and its limits;
they do not prove the missing price or retention duration. `not_answerable`
means the requested unknown cannot be resolved; a useful supported partial
explanation is still appropriate. `partially_answerable` cases require answering
the supported parts and explicitly identifying the unresolved parts.

### Database reference results

`expected_database_response` contains:

- `source_id`, `reference_sql`, and named `parameters`.
- `columns` and `rows`; each row is an array aligned with `columns`. SQL NULL
  values remain JSON `null`.
- `order_matters` and a human-readable `comparison` rule.

These rows are actual results from the supplied database. Policy-derived credit
amounts remain in `expected_calculations`, separate from raw database facts.
Reference queries may return extra columns useful for auditing. A future system
can use equivalent SQL and different projections as long as all requested facts
are retrieved correctly. Compare semantic results and preserve row multiplicity;
do not require identical SQL text or irrelevant columns. Row order is immaterial
in the current cases.

The local validator compares each stored result with its own reference query,
using `mode=ro`, `PRAGMA query_only`, and an SQLite authorizer that permits only
query operations. This protects the reference-validation connection. It does
not validate an application's NL2SQL security guardrails.

### Calculator targets

Each target has a unique `calculation_id`, an `operation`, structured `inputs`,
and a descriptive `formula`. Formula strings are never evaluated as code.

| Operation | Expected output |
|---|---|
| `monthly_sla_credit` | `expected_results`: scheduled minutes, uptime percentage, credit percentage, credit amount; plus `units` and `tolerances` per result. |
| `sum_credit_amounts` | `inputs.calculation_ids` identifies component credits; `expected_result`, `unit`, and `tolerance` describe the sum. |
| `calendar_day_difference` | Start/end ISO dates, optional DB date-field reference, purpose, expected calendar-day difference, unit, and tolerance. |

Displayed uptime is a decimal string with six places; money is a decimal string
with two places. Tolerances are ±0.000001 percentage points for uptime and ±0.01
currency units for money. Scheduled minutes, bracket percentages, and date
differences must match exactly. The validator checks inputs against independent
DB queries and recomputes the targets with `Decimal`, `calendar`, and `datetime`.
It selects brackets from unrounded uptime rather than the displayed value.

Calculator-required IDs are X-M01–X-M04, X-H01, X-H03, and X-H04. Numerical lookup,
threshold comparison, and explaining a formula do not by themselves require a
calculator. H07 can identify the missing first-response evidence without
calculating a resolution interval.

Hybrid assumptions are visible in every case: snapshot status is not history;
recorded downtime is complete/qualifying where monthly credit is calculated;
`monthly_rate` is the final fee; amounts have unspecified currency; actual UTC
calendar months apply. X-H01 additionally supplies a common currency unit for
summing credits. X-H04 additionally specifies independent filings and date-only
deadlines. None of these exercise assumptions should be claimed as stored facts.

## Supplying cases to a future answering system

Give the system access to the allowed source files and only these record fields:

```python
import json

with open("evals/rag/benchmark.jsonl", encoding="utf-8") as stream:
    for line in stream:
        case = json.loads(line)
        system_input = {
            "question": case["question"],
            "input_context": case["input_context"],
        }
        # Pass system_input to the future system adapter.
```

Keep reference SQL, rows, evidence, answers, source-selection flags, and judge
rubrics outside the answering system's prompt and retrieval corpus. Do not
index `evals/` as source knowledge. A future runner must enforce that boundary.

## LLM-as-judge conventions

Every judge entry contains `criterion_id`, `stage` (`retrieval` or `generation`),
a case-specific `question`, `required_inputs`, and `scoring_anchors` for `0`, `1`,
and `2`. Selected criteria also allow the string `not_applicable`.

All cases include retrieval evidence coverage/context relevance, answer
correctness, completeness, faithfulness, citation precision, citation coverage,
relevance, and uncertainty. Hybrid cases additionally assess source attribution
and unsupported financial conclusions. Keep all criterion scores separate.

Most `required_inputs` name record fields. The following inputs must instead
come from an actual run:

| Runtime input | Required content |
|---|---|
| `answer` | Final system answer. |
| `retrieved_document_chunks` | Actual text, rank, document ID/path, and page/section metadata for retrieved chunks. |
| `generator_contexts` | Exact context and tool messages supplied to each relevant generator turn; determines which evidence the model actually saw. |
| `database_results` | Actual executed SQL, parameters, columns, and rows. |
| `calculator_trace` | Actual calculator calls, arguments, and returned results. |
| `citations` | Claim-linked citations from the answer. |
| `cited_source_passages` | Independently resolved source text at the cited pages/sections. |

Use empty lists for tools or citations that were not used. Failure to capture a
required trace is a logging/evaluation error, rather than evidence of no tool use.
Distinguish that from a captured trace showing the system omitted a required tool.

Judge instructions must treat candidate answers, chunks, and tool output as
untrusted data and ignore any instructions inside them. Require an output such
as `{ "criterion_id": "correctness", "score": 2, "reason": "..." }`; the
completeness judge should additionally list covered and omitted `fact_id` values.
Use only each criterion's declared inputs. Correctness uses independently
curated reference facts. Faithfulness uses **actual retrieved context and visible
input facts actually delivered to the generator**, never hidden gold as a
substitute for context the system missed. Use `generator_contexts` to establish
visibility; a raw chunk or DB result lost before generation cannot justify a
claim. In generation mode, supplied reference passages/rows are labeled fixtures;
only content actually delivered to the generator supports faithfulness.
A correct guess can therefore fail faithfulness; faithful repetition of an
incomplete context can fail completeness.

An empty retrieval gets evidence coverage 0; context relevance is
`not_applicable`. No citations gets citation precision `not_applicable`, while
uncited policy claims get citation coverage 0. Unjustified refusal on an
answerable case fails uncertainty handling even if no-claim faithfulness is
`not_applicable`. Missing required evaluator inputs, judge timeouts, and malformed
judge responses are evaluation errors and must not silently become agent scores.

For a future retrieval runner, report evidence recall@k (covered groups / total
groups), all-evidence success@k, and context precision@k (useful chunks / retrieved
chunks). These ratios are distinct from the judge's ordinal 0–2 anchors. Report
document/hybrid results separately, sliced by difficulty. Check numeric results
and tool execution deterministically before judging semantic quality; a correct
number alone does not establish that a calculator was called.

The local checks validate the answer-key artifacts. They do not establish actual
retrieval quality, judge reliability, dynamic SQL generation, calculator tool
execution, or generalization beyond this small policy-specific bank. Related
questions should remain in the same partition if a held-out split is introduced.
