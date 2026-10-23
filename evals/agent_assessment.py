"""Offline trace checks and external semantic judging; never imported by the agent."""

import ast
import calendar
import csv
import hashlib
import json
import operator
import statistics
import subprocess
from collections import Counter
from datetime import date
from fractions import Fraction
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from adan.schemas import QueryResponse
from evals.rag.retrieval_judgments import build_annotations
from evals.rag.retrieval_metrics import score as retrieval_score

NOT_APPLICABLE = "NOT_APPLICABLE"
NO_REFERENCE = "NO_REFERENCE"
NOT_RUN = "NOT_RUN"
ERROR = "EVALUATION_ERROR"
INFRASTRUCTURE_ERROR = "INFRASTRUCTURE_ERROR"
NODE_COLUMNS = [
    f"{name}_score"
    for name in (
        "coordinator",
        "documents",
        "database",
        "aggregation",
        "generate",
        "tools",
        "guard",
        "finalize",
    )
]


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criterion_id: str
    score: int | None = Field(ge=0, le=2)
    reason: str


class CriteriaResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    criteria: list[Criterion]


class DatabaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    score: int = Field(ge=0, le=2)
    reason: str


class GuardVerdict(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_index: int
    supported: bool
    reason: str


def expected_route(case):
    if "expected_needs_docs" in case:
        return {"needs_docs": case["expected_needs_docs"], "needs_db": case["expected_needs_db"]}
    return {
        "needs_docs": bool(case["is_document_1_needed"] or case["is_document_2_needed"]),
        "needs_db": case["is_database_needed"],
    }


def exact_arithmetic(expression):
    """Independent bounded rational recomputation of a calculator expression."""
    if len(expression) > 1000:
        raise ValueError("Expression too long")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 100:
        raise ValueError("Expression too complex")
    operations = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Mod: operator.mod,
        ast.Pow: operator.pow,
    }

    def visit(node):
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = Fraction(ast.get_source_segment(expression, node).replace("_", ""))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in operations:
            left, right = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Pow) and (right.denominator != 1 or abs(right) > 100):
                raise ValueError("Unsafe exponent")
            value = operations[type(node.op)](left, right)
        else:
            raise ValueError("Unsupported arithmetic")
        if (
            abs(value) > 10**100
            or max(value.numerator.bit_length(), value.denominator.bit_length()) > 4096
        ):
            raise ValueError("Arithmetic budget exceeded")
        return value

    return visit(tree.body)


def calculator_checks(response, case):
    calls = response["calculator_trace"]
    checked, values = [], []
    for call in calls:
        correct = False
        if call["status"] == "ok":
            inputs, output = call["inputs"], call["output"]
            try:
                if inputs["operation"] == "evaluate":
                    expected = exact_arithmetic(inputs["expression"])
                    actual = Fraction(output["numerator"], output["denominator"])
                elif inputs["operation"] == "month_minutes":
                    expected = calendar.monthrange(inputs["year"], inputs["month"])[1] * 1440
                    actual = Fraction(str(output["value"]))
                else:
                    expected = (
                        date.fromisoformat(inputs["end_date"])
                        - date.fromisoformat(inputs["start_date"])
                    ).days
                    actual = Fraction(str(output["value"]))
                correct = actual == expected
                if correct:
                    values.append(actual)
            except (ArithmeticError, ValueError, KeyError, TypeError):
                correct = False
        checked.append({"event_id": call["event_id"], "correct": correct})
    targets = []
    for calculation in case.get("expected_calculations", []):
        results = calculation.get("expected_results", {"value": calculation.get("expected_result")})
        tolerances = calculation.get("tolerances", {"value": calculation.get("tolerance", 0)})
        for name, value in results.items():
            tolerance = Fraction(str(tolerances.get(name, 0)))
            matched = any(abs(v - Fraction(str(value))) <= tolerance for v in values)
            targets.append(
                {
                    "calculation_id": calculation["calculation_id"],
                    "target": name,
                    "expected": value,
                    "matched": matched,
                }
            )
    return {
        "executions": checked,
        "reference_targets": targets,
        "execution_accuracy": sum(c["correct"] for c in checked) / len(checked)
        if checked
        else None,
        "reference_value_coverage": sum(t["matched"] for t in targets) / len(targets)
        if targets
        else None,
    }


def projected_database_check(reference, results):
    """Diagnostic only: shared exact column names; semantic judge accepts other projections."""
    diagnostics = []
    for result in results:
        columns = [c for c in reference["columns"] if c in result["columns"]]
        if not columns:
            continue
        expected_indices = [reference["columns"].index(c) for c in columns]
        actual_indices = [result["columns"].index(c) for c in columns]
        expected = Counter(tuple(row[i] for i in expected_indices) for row in reference["rows"])
        actual = Counter(tuple(row[i] for i in actual_indices) for row in result["rows"])
        diagnostics.append(
            {
                "columns": columns,
                "exact_multiset_match": actual == expected,
                "truncated": result.get("truncated", False),
            }
        )
    return diagnostics


def resolve_citations(response, root):
    passages, errors = [], []
    sources = root / "data" / "documents"
    for citation in response["citations"]:
        name = citation.get("source_file", "")
        path = sources / Path(name).name
        pages = citation.get("page_numbers") or [citation.get("page_number")]
        for page in pages:
            if (
                path.parent != sources
                or not path.is_file()
                or type(page) is not int
                or not 1 <= page <= 20
            ):
                errors.append(
                    {"chunk_id": citation.get("chunk_id"), "error": "Invalid source location"}
                )
                continue
            result = subprocess.run(
                ["pdftotext", "-f", str(page), "-l", str(page), "-layout", str(path), "-"],
                capture_output=True,
                text=True,
                check=True,
            )
            passages.append(
                {
                    "chunk_id": citation["chunk_id"],
                    "source_file": name,
                    "page": page,
                    "text": result.stdout,
                }
            )
    return passages, errors


def guard_inputs(response):
    candidates = []
    for index, guard in enumerate(response["guardrail_history"]):
        candidate = guard["candidate"]
        matching = [
            event
            for event in response["execution_trace"]
            if event["name"] == "model.generate"
            and any(
                call.get("name") == "submit_answer" and call.get("args") == candidate
                for call in event.get("output", {}).get("message", {}).get("tool_calls", [])
            )
        ]
        if not matching:
            raise ValueError("Cannot establish candidate visibility")
        # Match repeated identical submissions to their corresponding generator turn.
        occurrence = sum(g["candidate"] == candidate for g in response["guardrail_history"][:index])
        event = matching[min(occurrence, len(matching) - 1)]
        candidates.append(
            {
                "candidate_index": index,
                "candidate": candidate,
                "messages": event["inputs"]["messages"],
            }
        )
    return candidates


def unknown_candidate_citations(candidate):
    """Check citation identifiers against the evidence visible to this candidate."""
    cited = set(candidate["candidate"]["citation_ids"])
    if not cited:
        return []
    for message in candidate["messages"]:
        content = message.get("content", "")
        if message.get("role") != "system" or not isinstance(content, str):
            continue
        _, separator, evidence = content.partition("\nEvidence:\n")
        if separator:
            visible = {c["chunk_id"] for c in json.loads(evidence)["documents"]}
            return sorted(cited - visible)
    raise ValueError("Candidate's source evidence is missing from its visible context")


def base_assessment(suite, case, record, annotations):
    row = {
        "suite": suite,
        "question_id": case["question_id"],
        "question": case["question"],
        "difficulty": case.get("difficulty", ""),
        "category": case.get("category", "routing"),
        "reference_answerability": case.get("answerability", ""),
        "split": case.get("split", ""),
        "http_status": record.get("http_status"),
        "collection_error": record.get("error") or "",
        **dict.fromkeys(NODE_COLUMNS, NO_REFERENCE),
    }
    details = {"checks": {}, "judge_errors": []}
    response = record.get("response")
    if record.get("error") or not response:
        row.update(dict.fromkeys(NODE_COLUMNS, ERROR))
        return row, details
    QueryResponse.model_validate(response)
    expected = expected_route(case)
    provider_errors = [
        e
        for e in response["execution_trace"]
        if isinstance(e.get("output"), dict) and e["output"].get("http_status") == 429
    ]
    guards = response["guardrail_history"]
    if response["stop_reason"] == "completed":
        final_matches = (
            bool(guards)
            and guards[-1]["passed"]
            and all(
                response[key] == guards[-1]["candidate"][key]
                for key in ("answer", "status", "missing_information")
            )
        )
        if final_matches:
            final_matches = [c["chunk_id"] for c in response["citations"]] == list(
                dict.fromkeys(guards[-1]["candidate"]["citation_ids"])
            )
    else:
        final_matches = response["status"] != "complete" and bool(response["missing_information"])
    row.update(
        {
            "run_id": response["run_id"],
            "status": response["status"],
            "stop_reason": response["stop_reason"],
            "duration_ms": response["timings"]["duration_ms"],
            "model_calls": response["usage"]["model_calls"],
            "tool_calls": response["usage"]["tool_calls"],
            "total_tokens": response["usage"]["total_tokens"],
            "cost": response["usage"]["cost"],
            "text_model": response["effective_limits"]["text_model"],
            "router_model": response["effective_limits"]["router_model"],
            "router_fallback_model": response["effective_limits"]["router_fallback_model"],
            "expected_route": json.dumps(expected, sort_keys=True),
            "actual_route": json.dumps(response["route"], sort_keys=True),
            "coordinator_score": int(response["route"] == expected),
            "failures": json.dumps(response["failures"]),
            "provider_429_attempts": len(provider_errors),
            "router_fallback_used": any(
                e["name"] == "model.coordinator" and e["inputs"].get("fallback")
                for e in response["execution_trace"]
            ),
            "finalize_score": int(
                response["question"] == record["request"]["question"].strip()
                and response["input_context"] == record["request"]["input_context"]
                and all(e["status"] != "running" for e in response["execution_trace"])
                and final_matches
            ),
        }
    )
    if suite != "rag":
        return row, details
    judgments = annotations[case["question_id"]]
    ranking = response["retrieved_document_chunks"]
    for k in (5, 10, 20):
        metrics = retrieval_score(ranking, judgments, k)
        details["checks"][f"retrieval_at_{k}"] = metrics
        for key in ("evidence_recall", "all_evidence_success", "context_precision"):
            row[f"{key}_at_{k}"] = metrics[key]
    row["documents_score"] = row["evidence_recall_at_20"]
    aggregated = [c for artifact in response["aggregation_artifacts"] for c in artifact["chunks"]]
    acquired = retrieval_score(ranking, judgments, max(1, len(ranking)))
    kept = retrieval_score(aggregated, judgments, max(1, len(aggregated)))
    acquired_groups = set(acquired["covered_requirements"])
    row["aggregation_score"] = (
        len(acquired_groups & set(kept["covered_requirements"])) / len(acquired_groups)
        if acquired_groups
        else NOT_APPLICABLE
    )
    details["checks"]["calculator"] = checks = calculator_checks(response, case)
    row["calculator_execution_accuracy"] = checks["execution_accuracy"]
    row["calculator_reference_value_coverage"] = checks["reference_value_coverage"]
    row["tools_score"] = (
        checks["execution_accuracy"]
        if checks["executions"]
        else 0
        if case["is_calculator_needed"]
        else NOT_APPLICABLE
    )
    if case["is_database_needed"]:
        details["checks"]["database_projection"] = projected_database_check(
            case["expected_database_response"], response["database_results"]
        )
    else:
        row["database_score"] = NOT_APPLICABLE
    row["generate_score"] = ERROR
    row["guard_score"] = NOT_RUN if not response["guardrail_history"] else ERROR
    return row, details


def apply_execution_limits(row, details, response, case):
    """Keep upstream/provider failures out of intrinsic node-score denominators."""
    stages = {
        "coordinator": "coordinator",
        "documents": "documents",
        "search_documents": "documents",
        "database": "database",
        "query_database": "database",
        "generate": "generate",
        "guard": "guard",
        "calculate": "tools",
    }
    excluded = {}
    infrastructure_affected = False
    for failure in response["failures"]:
        kind = failure.get("error_type", "")
        if not any(
            name in kind for name in ("OpenAI", "API", "RateLimit", "Connection", "Timeout")
        ):
            continue
        infrastructure_affected = True
        node = stages.get(failure["stage"])
        if node and row[node + "_score"] != NO_REFERENCE:
            excluded[node + "_score"] = INFRASTRUCTURE_ERROR
    names = {e["name"] for e in response["execution_trace"]}
    if row["suite"] == "rag":
        for node, event in (
            ("documents", "model.rewrite"),
            ("database", "model.formulate"),
            ("generate", "model.generate"),
        ):
            if row[node + "_score"] != NOT_APPLICABLE and event not in names:
                excluded[node + "_score"] = NOT_RUN
        if (
            not response["calculator_trace"]
            and case["is_calculator_needed"]
            and response["stop_reason"] != "completed"
        ):
            excluded["tools_score"] = NOT_RUN
    details["observed_scores_before_exclusion"] = {key: row[key] for key in excluded}
    row.update(excluded)
    row["infrastructure_affected"] = infrastructure_affected


async def snapshot_corpus(client, output, qdrant_url, fingerprint):
    response = await client.get(qdrant_url + "/collections")
    response.raise_for_status()
    names = [
        c["name"]
        for c in response.json()["result"]["collections"]
        if c["name"].endswith("_" + fingerprint[:16])
    ]
    if len(names) != 1:
        raise ValueError("Cannot uniquely identify the active Qdrant collection")
    corpus, offset = [], None
    while True:
        result = await client.post(
            qdrant_url + f"/collections/{names[0]}/points/scroll",
            json={
                "limit": 256,
                "with_payload": True,
                "with_vector": False,
                "offset": offset,
            },
        )
        result.raise_for_status()
        data = result.json()["result"]
        for point in data["points"]:
            metadata = point["payload"]
            if metadata["index_fingerprint"] != fingerprint:
                raise ValueError("Corpus provenance mismatch")
            node = json.loads(metadata["_node_content"])
            corpus.append({"chunk_id": node["id_"], "text": node["text"], "metadata": metadata})
        offset = data["next_page_offset"]
        if offset is None:
            break
    return corpus


def annotations_for(corpus, cases):
    annotations, _ = build_annotations(cases, corpus)
    return annotations


def write_reports(output, assessments):
    rows = [a["row"] for a in assessments]
    if not rows:
        return
    leading = ["suite", "question_id", "question", *NODE_COLUMNS]
    fields = leading + sorted(set().union(*(r.keys() for r in rows)) - set(leading))
    path = output / "node_assessments.csv"
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    summary = {"questions": len(rows), "suites": {}, "node_scores": {}}
    for suite in ("rag", "coordinator"):
        selected = [r for r in rows if r["suite"] == suite]
        summary["suites"][suite] = {
            "questions": len(selected),
            "status": dict(Counter(r.get("status", ERROR) for r in selected)),
            "stop_reasons": dict(Counter(r.get("stop_reason", ERROR) for r in selected)),
        }
    for column in NODE_COLUMNS:
        numbers = [r[column] for r in rows if type(r[column]) in (int, float)]
        summary["node_scores"][column] = {
            "mean": statistics.mean(numbers) if numbers else None,
            "scored_questions": len(numbers),
            "unscored": dict(
                Counter(str(r[column]) for r in rows if type(r[column]) not in (int, float))
            ),
        }
    summary["judge_errors"] = sum(len(a["details"]["judge_errors"]) for a in assessments)
    summary["response_files"] = len(list((output / "runs").glob("*/*.json")))
    summary["provider_429_attempts"] = sum(r.get("provider_429_attempts", 0) for r in rows)
    summary["router_fallback_runs"] = sum(r.get("router_fallback_used", False) for r in rows)
    summary["median_duration_ms"] = (
        statistics.median(r["duration_ms"] for r in rows if "duration_ms" in r)
        if any("duration_ms" in r for r in rows)
        else None
    )
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    table = []
    for column, stats in summary["node_scores"].items():
        mean = f"{stats['mean']:.3f}" if stats["mean"] is not None else "unscored"
        table.append(f"| {column} | {mean} | {stats['scored_questions']} | {stats['unscored']} |")
    lines = [
        "# Compose agent evaluation",
        "",
        f"Assessed **{len(rows)} questions**. See [node_assessments.csv](node_assessments.csv) "
        "for one row per question and [summary.json](summary.json) for counts/denominators.",
        "",
        "| Node diagnostic | Mean (0–1) | Scored questions | Unscored reasons |",
        "|---|---:|---:|---|",
        *table,
        "",
        "## What the scores mean",
        "",
        "- **Coordinator:** exact match against the benchmark's expected source flags.",
        "- **Documents:** cumulative required-evidence recall@20 using existing reviewed "
        "chunk annotations, checked against the active corpus. Includes follow-up searches.",
        "- **Database:** external semantic judge of requested raw DB facts versus reference "
        "rows; equivalent SQL/projections/order are accepted (0, 0.5, 1).",
        "- **Aggregation:** fraction of acquired required evidence groups still present "
        "in aggregation outputs, using annotated stable chunk IDs. Current aggregation "
        "is a passthrough; this is retention, not a new algorithm benchmark.",
        "- **Generate:** benchmark correctness rubric score divided by two. Completeness, "
        "faithfulness, citations, relevance and uncertainty remain separate judge columns (0–2).",
        "- **Tools:** independently recomputed calculator execution accuracy. Required "
        "calculator omission scores zero if the generator finished; blocked/unreached tools "
        "are NOT_RUN. Reference numeric-value coverage is a separate diagnostic: presence "
        "of a number alone does not prove its meaning or the correct formula.",
        "- **Guard:** agreement with deterministic citation-ID validation, then a separate "
        "Luna judge using each candidate's own visible context. Unknown IDs require rejection "
        "even if Luna finds the prose supported. Original Luna judgments are preserved.",
        "- **Finalize:** JSON contract, input identity, finished traces, and faithful return "
        "of the verified candidate (or an explicit qualified result after interruption). "
        "A score of one here does not mean the answer is correct.",
        "",
        "NO_REFERENCE means the dataset supplies no expected result for that node. "
        "The four routing-only cases therefore do not get invented answer/SQL scores. "
        "NOT_APPLICABLE means no required operation/evidence to score. NOT_RUN means the "
        "node was not reached. INFRASTRUCTURE_ERROR excludes affected node scores from "
        "means; EVALUATION_ERROR means collection/judge evidence was invalid. "
        "Observed pre-exclusion scores and detailed reasons remain in assessments/.",
        "",
        "## Evidence and limits",
        "",
        "- [selection.json](selection.json) records the coverage-based 12-case selection "
        "and reused responses. It is a purposive diagnostic sample, not an unbiased estimate "
        "of performance across all 112 cases. Selection occurred after collection began.",
        "- runs/{suite}/{question_id}.json preserves each exact request, full API response "
        "and trace. assessments/ stores checks and reasons; judges/ stores judge requests, "
        "responses, model IDs, usage and failed attempts, without authentication headers.",
        "- Expected answers/rows/rubrics stay outside the agent. The Compose image was "
        "checked to exclude evals, and its PDFs/database match the benchmark source hashes.",
        "- Citation checks use actual PDF pages resolved independently with pdftotext. "
        "Faithfulness/guard judging is separate from answer-key-based judging, using exact "
        "generator visibility and no hidden answer key.",
        "- Final LLM judgments use **Luna subagents (gpt-6-luna)**, as requested. "
        "All three available workers were dispatched in parallel with 26 schema-constrained "
        "assessment jobs. luna_jobs/ records their inputs; luna_results/ records their "
        "actual judgments; luna_judges/ links validated results to input hashes. "
        "Earlier Nemotron and Antigravity attempts are audit-only and excluded from "
        "the final CSV. Antigravity reached its account quota before the user requested Luna. "
        "Judgments remain uncalibrated model assessments, not objective truth.",
        f"- Saved runs contain **{summary['provider_429_attempts']} HTTP 429 attempts**, "
        f"including recovered retries; **{summary['router_fallback_runs']} runs** used "
        "the configured routing fallback. The primary Mammoth chat requests returned "
        "HTTP 400; these are fallback-system results, not proof of primary-router quality.",
        "- All agent models remain free OpenRouter endpoints; no paid OpenRouter "
        "endpoint was used. Final judgments use the requested Luna subagents. "
        "Unknown token/cost totals remain null, "
        "including failed attempts without provider usage. No inferred total cost is reported.",
        "- Node diagnostics describe behavior inside an end-to-end run. They are not "
        "causally isolated node experiments; upstream mistakes can affect downstream outputs. "
        "No single blended overall score is produced.",
        "- Final-answer faithfulness uses the exact final generator input, which retains "
        "the supplied conversation and current evidence. Each guard candidate is judged "
        "separately against its own exact input to avoid crediting later evidence. "
        "All original turns remain in the saved agent responses.",
        "",
        "The original broader collection is retained separately at "
        "../2026-10-23-compose/ after the user reduced the scope to 12 questions. "
        "It is excluded from this CSV and its denominators.",
        "",
    ]
    (output / "REPORT.md").write_text("\n".join(lines))
    checksums = {
        str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*"))
        if p.is_file() and p.name != "checksums.json" and p.suffix not in (".tmp", ".log")
    }
    (output / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n")
