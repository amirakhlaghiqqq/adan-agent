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


class VisibilityResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    faithfulness: Criterion
    guard_candidates: list[GuardVerdict]


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


def base_assessment(suite, case, record, annotations):
    row = {
        "suite": suite,
        "question_id": case["question_id"],
        "question": case["question"],
        "difficulty": case.get("difficulty", ""),
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
            "expected_route": json.dumps(expected, sort_keys=True),
            "actual_route": json.dumps(response["route"], sort_keys=True),
            "coordinator_score": int(response["route"] == expected),
            "failures": json.dumps(response["failures"]),
            "finalize_score": int(
                response["question"] == record["request"]["question"].strip()
                and response["input_context"] == record["request"]["input_context"]
                and all(e["status"] != "running" for e in response["execution_trace"])
                and (
                    response["stop_reason"] != "completed"
                    or bool(response["guardrail_history"])
                    and response["guardrail_history"][-1]["passed"]
                )
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
    summary["median_duration_ms"] = (
        statistics.median(r["duration_ms"] for r in rows if "duration_ms" in r)
        if any("duration_ms" in r for r in rows)
        else None
    )
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    checksums = {
        str(p.relative_to(output)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(output.rglob("*.json"))
        if p.name != "checksums.json"
    }
    (output / "checksums.json").write_text(json.dumps(checksums, indent=2) + "\n")
