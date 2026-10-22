#!/usr/bin/env python3
"""Validate benchmark truth locally; never call an answering system or LLM judge."""

import argparse
import calendar
import copy
import hashlib
import json
import re
import sqlite3
import subprocess
import sys
import unicodedata
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
FIELDS = {
    "schema_version": str, "question_id": str, "question": str,
    "difficulty": str, "category": str,
    "is_document_1_needed": bool, "is_document_2_needed": bool,
    "is_database_needed": bool, "is_calculator_needed": bool,
    "input_context": list, "required_document_evidence": list,
    "expected_database_response": (dict, type(None)),
    "expected_calculations": list, "expected_answer": str,
    "required_answer_facts": list, "answerability": str,
    "missing_information": list, "prohibited_claims": list,
    "llm_judge_questions": list,
}
CRITERIA = {
    "evidence_coverage", "context_relevance", "correctness", "completeness",
    "faithfulness", "citation_precision", "citation_coverage", "relevance", "uncertainty",
}
RUNTIME_INPUTS = {
    "answer", "retrieved_document_chunks", "database_results", "calculator_trace",
    "citations", "cited_source_passages",
}


class InvalidBenchmark(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InvalidBenchmark(message)


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def strings(value, label, allow_empty=False):
    require(isinstance(value, list), f"{label}: expected list")
    require(allow_empty or bool(value), f"{label}: empty list")
    require(all(nonempty(x) for x in value), f"{label}: expected nonempty strings")


def normalize(text):
    """NFC and whitespace only; preserve punctuation, case, and PDF hyphenation."""
    return " ".join(unicodedata.normalize("NFC", text).split())


def strict_json(text):
    def unique_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"duplicate JSON key {key!r}")
            result[key] = value
        return result

    def invalid_constant(value):
        raise InvalidBenchmark(f"non-finite JSON number {value}")

    return json.loads(text, object_pairs_hook=unique_pairs, parse_constant=invalid_constant)


def bank_questions():
    result = {}
    for name in ("questions.md", "hybrid_questions.md"):
        text = (HERE / name).read_text(encoding="utf-8")
        for match in re.finditer(
            r"^### ((?:X-)?[EMH]\d{2}) — [^\n]+\n(.*?)(?=^### |^## |\Z)", text, re.M | re.S
        ):
            question = re.search(r"\*\*Question:\*\*\s*(.*?)(?=\n\n\*\*|\Z)", match[2], re.S)
            require(question is not None, f"{match[1]}: missing Markdown question")
            require(match[1] not in result, f"duplicate Markdown ID {match[1]}")
            result[match[1]] = question[1].strip()
    return result


def check_sources(manifest):
    require(manifest.get("schema_version") == "1.0", "manifest: unsupported schema version")
    sources = manifest.get("sources")
    require(isinstance(sources, dict), "manifest: missing sources")
    require(set(sources) == {
        "document_1", "document_2", "database", "database_schema", "database_seed",
        "document_questions", "hybrid_questions",
    }, "manifest: unexpected source IDs")
    for source_id, source in sources.items():
        require(isinstance(source, dict), f"{source_id}: expected source object")
        for field in ("path", "version", "sha256"):
            require(nonempty(source.get(field)), f"{source_id}: invalid {field}")
        path = (ROOT / source["path"]).resolve()
        require(path.is_relative_to(ROOT), f"{source_id}: path escapes repository")
        require(path.is_file(), f"{source_id}: missing {source['path']}")
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        require(actual == source["sha256"], f"{source_id}: SHA-256 mismatch; source snapshot changed")
    for source_id, doc_id, count in (
        ("document_1", "DOC-BIL-2024-V3", 4), ("document_2", "DOC-SLA-2024-V2", 6)
    ):
        require(sources[source_id].get("document_id") == doc_id, f"{source_id}: incorrect document mapping")
        require(sources[source_id].get("page_count") == count, f"{source_id}: incorrect page count")


class SourceContext:
    def __init__(self, manifest):
        self.sources = manifest["sources"]
        self.pages = {}
        for key in ("document_1", "document_2"):
            source = self.sources[key]
            result = subprocess.run(
                ["pdftotext", "-layout", str(ROOT / source["path"]), "-"],
                check=True, capture_output=True, text=True, encoding="utf-8",
            )
            pages = result.stdout.split("\f")
            if not pages[-1].strip():
                pages.pop()
            require(len(pages) == source["page_count"], f"{key}: extracted PDF page count changed")
            self.pages[key] = [normalize(page) for page in pages]
        self.connection = sqlite3.connect(
            (ROOT / self.sources["database"]["path"]).resolve().as_uri() + "?mode=ro", uri=True
        )
        self.connection.execute("PRAGMA query_only = ON")
        allowed = {sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION, sqlite3.SQLITE_RECURSIVE}
        self.connection.set_authorizer(
            lambda action, *_: sqlite3.SQLITE_OK if action in allowed else sqlite3.SQLITE_DENY
        )
        self.questions = bank_questions()
        self.evidence_by_id = {}
        for table, count in self.sources["database"]["table_counts"].items():
            require(table in {"customers", "subscriptions", "incident_tickets"}, "invalid manifest table")
            actual = self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            require(actual == count, f"database: {table} count changed")

    def close(self):
        self.connection.close()

    def query(self, sql, parameters):
        require(nonempty(sql) and re.match(r"^\s*(SELECT|WITH)\b", sql, re.I), "reference_sql: expected SELECT/WITH")
        cursor = self.connection.execute(sql, parameters)
        return [x[0] for x in cursor.description], [list(row) for row in cursor.fetchall()]


def compare_number(actual, expected, tolerance, label):
    require(type(expected) in (str, int, float), f"{label}: invalid numeric type")
    require(type(tolerance) in (int, float), f"{label}: invalid tolerance type")
    a, e, t = Decimal(str(actual)), Decimal(str(expected)), Decimal(str(tolerance))
    require(a.is_finite() and e.is_finite() and t.is_finite() and t >= 0, f"{label}: invalid numeric value")
    require(abs(a - e) <= t, f"{label}: expected {expected}, independently computed {actual}")


def visible_dates(question):
    months = {name: index for index, name in enumerate(calendar.month_name) if name}
    return {
        date(int(year), months[month], int(day)).isoformat()
        for month, day, year in re.findall(
            r"\b(" + "|".join(months) + r") (\d{1,2}), (\d{4})\b", question
        )
    }


def monthly_credit(inputs, ctx):
    require(set(inputs) == {"customer_id", "month", "tier", "monthly_rate", "downtime_minutes"}, "credit: invalid inputs")
    require(type(inputs["customer_id"]) is int, "credit: invalid customer_id")
    require(isinstance(inputs["month"], str) and re.fullmatch(r"\d{4}-\d{2}", inputs["month"]), "credit: invalid month")
    stored = ctx.connection.execute(
        "SELECT c.tier, s.monthly_rate FROM customers c JOIN subscriptions s USING(customer_id) WHERE customer_id = ?",
        (inputs["customer_id"],),
    ).fetchall()
    require(len(stored) == 1, "credit: expected exactly one applicable snapshot subscription")
    tier, fee = stored[0]
    downtime = ctx.connection.execute(
        "SELECT COALESCE(SUM(downtime_minutes), 0) FROM incident_tickets WHERE customer_id = ? AND substr(reported_at, 1, 7) = ?",
        (inputs["customer_id"], inputs["month"]),
    ).fetchone()[0]
    require((tier, fee, downtime) == (inputs["tier"], inputs["monthly_rate"], inputs["downtime_minutes"]), "credit: inputs disagree with live read-only DB")
    year, month = map(int, inputs["month"].split("-"))
    minutes = calendar.monthrange(year, month)[1] * 24 * 60
    require(0 <= downtime <= minutes, "credit: downtime outside month")
    uptime = Decimal(minutes - downtime) / Decimal(minutes) * 100
    # Independently encode the policy brackets; never evaluate dataset formula strings.
    if tier == "Starter":
        percent = 0
    elif tier == "Enterprise":
        percent = 0 if uptime >= Decimal("99.99") else 10 if uptime >= Decimal("99.90") else 25 if uptime >= 99 else 50 if uptime >= 95 else 100
    else:
        require(tier == "Professional", "credit: unknown tier")
        percent = 0 if uptime >= Decimal("99.90") else 10 if uptime >= 99 else 25 if uptime >= 98 else 50 if uptime >= 95 else 100
    amount = Decimal(str(fee)) * Decimal(percent) / 100
    return {"scheduled_minutes": minutes, "uptime_percentage": uptime,
            "credit_percentage": percent, "credit_amount": amount}


def validate_calculations(record, ctx, database_rows):
    computed = {}
    selected = {row["customer_id"] for row in database_rows}
    for calc in record["expected_calculations"]:
        require(isinstance(calc, dict), "calculation: expected object")
        cid = calc.get("calculation_id")
        require(nonempty(cid) and cid not in computed, "calculation: invalid/duplicate ID")
        require(nonempty(calc.get("formula")), f"{cid}: missing formula")
        inputs = calc.get("inputs")
        require(isinstance(inputs, dict), f"{cid}: missing inputs")
        operation = calc.get("operation")
        if operation == "monthly_sla_credit":
            require(inputs.get("customer_id") in selected, f"{cid}: customer outside reference query results")
            result = monthly_credit(inputs, ctx)
            expected, tolerances = calc.get("expected_results"), calc.get("tolerances")
            require(isinstance(expected, dict) and set(expected) == set(result), f"{cid}: invalid expected_results")
            require(isinstance(expected["uptime_percentage"], str) and re.fullmatch(r"\d+\.\d{6}", expected["uptime_percentage"]), f"{cid}: uptime must display six decimals")
            require(isinstance(expected["credit_amount"], str) and re.fullmatch(r"\d+\.\d{2}", expected["credit_amount"]), f"{cid}: amount must display two decimals")
            require(tolerances == {"scheduled_minutes": 0, "uptime_percentage": 0.000001, "credit_percentage": 0, "credit_amount": 0.01}, f"{cid}: incorrect tolerances")
            require(calc.get("units") == {"scheduled_minutes": "minutes", "uptime_percentage": "percent", "credit_percentage": "percent of monthly fee", "credit_amount": "currency units"}, f"{cid}: incorrect units")
            for key, actual in result.items():
                compare_number(actual, expected[key], tolerances[key], f"{cid}.{key}")
            computed[cid] = result
        elif operation == "sum_credit_amounts":
            refs = inputs.get("calculation_ids")
            strings(refs, f"{cid}.calculation_ids")
            require(len(set(refs)) == len(refs), f"{cid}: duplicate credit summand")
            require(all(ref in computed and isinstance(computed[ref], dict) for ref in refs), f"{cid}: missing credit reference")
            require(set(refs) == {key for key, val in computed.items() if isinstance(val, dict)}, f"{cid}: total omits computed customer")
            require(any("same unspecified currency" in s for s in record["input_context"]), f"{cid}: missing shared-currency assumption")
            actual = sum((computed[ref]["credit_amount"] for ref in refs), Decimal(0))
            require(calc.get("unit") == "currency units" and calc.get("tolerance") == 0.01, f"{cid}: invalid total units/tolerance")
            compare_number(actual, calc.get("expected_result"), calc["tolerance"], cid)
            computed[cid] = actual
        elif operation == "calendar_day_difference":
            start, end = date.fromisoformat(inputs["start_date"]), date.fromisoformat(inputs["end_date"])
            field = inputs.get("database_date_field")
            if field:
                require(field == "renewal_date", f"{cid}: unsupported database date field")
                require(inputs["end_date"] in {row[field] for row in database_rows}, f"{cid}: date differs from DB")
                require(inputs["start_date"] in visible_dates(record["question"]), f"{cid}: notice date absent from visible question")
            else:
                month_end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
                require(start == month_end, f"{cid}: filing window must start at month end")
                credit_months = {c["inputs"]["month"] for c in record["expected_calculations"] if c["operation"] == "monthly_sla_credit"}
                require(start.strftime("%Y-%m") in credit_months, f"{cid}: filing month differs from credit month")
                require(inputs["end_date"] in visible_dates(record["question"]), f"{cid}: filing date absent from visible question")
            require(nonempty(calc.get("purpose")), f"{cid}: missing date purpose")
            require(calc.get("unit") == "calendar days" and calc.get("tolerance") == 0, f"{cid}: invalid date units/tolerance")
            compare_number((end - start).days, calc.get("expected_result"), 0, cid)
            computed[cid] = (end - start).days
        else:
            raise InvalidBenchmark(f"{cid}: unsupported calculation operation {operation!r}")


def validate_record(record, ctx):
    require(isinstance(record, dict), "record must be a JSON object")
    require(set(record) == set(FIELDS), f"fields: missing {sorted(set(FIELDS)-set(record))}; unexpected {sorted(set(record)-set(FIELDS))}")
    for key, kind in FIELDS.items():
        require(isinstance(record[key], kind), f"{key}: incorrect type")
        if kind is str:
            require(nonempty(record[key]), f"{key}: empty string")
    qid = record["question_id"]
    require(record["schema_version"] == "1.0", "unsupported schema_version")
    require(qid in ctx.questions, "ID absent from existing question banks")
    require(record["question"] == ctx.questions[qid], "question differs from original bank")
    require(record["difficulty"] == {"E": "easy", "M": "medium", "H": "hard"}[qid.replace("X-", "")[0]], "difficulty disagrees with ID")
    hybrid = qid.startswith("X-")
    require(record["category"] == ("hybrid" if hybrid else "document"), "category disagrees with ID")
    require(record["is_database_needed"] == hybrid, "database flag inconsistent with category")
    require(record["is_calculator_needed"] == bool(record["expected_calculations"]), "calculator flag inconsistent with targets")
    strings(record["input_context"], "input_context")
    strings(record["missing_information"], "missing_information", allow_empty=True)
    strings(record["prohibited_claims"], "prohibited_claims")
    require(record["answerability"] in {"answerable", "partially_answerable", "not_answerable"}, "invalid answerability")
    require((record["answerability"] == "answerable") == (not record["missing_information"]), "answerability inconsistent with information gaps")
    require(record["required_answer_facts"], "missing required answer facts")
    fact_ids = set()
    for fact in record["required_answer_facts"]:
        require(isinstance(fact, dict) and set(fact) == {"fact_id", "fact"}, "invalid answer fact")
        require(nonempty(fact["fact"]) and re.fullmatch(re.escape(qid) + r"-F\d{2}", fact["fact_id"] or ""), "invalid fact text or ID")
        require(fact["fact_id"] not in fact_ids, "duplicate fact ID")
        fact_ids.add(fact["fact_id"])
    docs, group_ids = set(), set()
    require(record["required_document_evidence"], "missing document evidence")
    for group in record["required_document_evidence"]:
        require(isinstance(group, dict) and set(group) == {"requirement_id", "role", "alternatives"}, "invalid evidence group")
        gid = group["requirement_id"]
        require(isinstance(gid, str) and re.fullmatch(re.escape(qid) + r"-R\d{2}", gid), "invalid evidence requirement ID")
        require(gid not in group_ids, "duplicate evidence requirement ID")
        group_ids.add(gid)
        require(group["role"] in {"supporting_policy", "limiting_or_adjacent_policy"}, f"{gid}: invalid evidence role")
        require(isinstance(group["alternatives"], list) and group["alternatives"], f"{gid}: no alternatives")
        for span in group["alternatives"]:
            require(isinstance(span, dict) and set(span) == {"evidence_id", "source_id", "document_id", "path", "page", "section", "text"}, f"{gid}: invalid span")
            sid = span["source_id"]
            require(sid in ctx.pages, f"{gid}: unknown document")
            source = ctx.sources[sid]
            require(span["document_id"] == source["document_id"] and span["path"] == source["path"], f"{gid}: incorrect document metadata")
            require(type(span["page"]) is int and 1 <= span["page"] <= len(ctx.pages[sid]), f"{gid}: invalid rendered page")
            require(all(nonempty(span[k]) for k in ("evidence_id", "section", "text")), f"{gid}: empty evidence field")
            require(normalize(span["text"]) in ctx.pages[sid][span["page"]-1], f"{gid}: passage not found on cited PDF page")
            prior = ctx.evidence_by_id.get(span["evidence_id"])
            require(prior is None or prior == span, f"{gid}: stable evidence ID has conflicting content")
            ctx.evidence_by_id[span["evidence_id"]] = span
            docs.add(sid)
    for sid in ("document_1", "document_2"):
        require(record[f"is_{sid}_needed"] == (sid in docs), f"{sid}: source flag inconsistent with evidence")
    if hybrid:
        require(docs == {"document_1", "document_2"}, "hybrid case must require both PDFs")
        require(len(record["input_context"]) >= 6, "missing common hybrid assumptions")
    db, live_rows = record["expected_database_response"], []
    if hybrid:
        require(isinstance(db, dict) and set(db) == {"source_id", "reference_sql", "parameters", "columns", "rows", "order_matters", "comparison"}, "invalid expected_database_response")
        require(db["source_id"] == "database" and isinstance(db["parameters"], dict), "invalid database source/parameters")
        require(type(db["order_matters"]) is bool and nonempty(db["comparison"]), "missing DB comparison policy")
        strings(db["columns"], "database columns")
        require(len(set(db["columns"])) == len(db["columns"]), "duplicate DB columns")
        require(isinstance(db["rows"], list), "rows must be a list")
        require(all(isinstance(row, list) and len(row) == len(db["columns"]) for row in db["rows"]), "invalid DB row shape")
        columns, rows = ctx.query(db["reference_sql"], db["parameters"])
        require(columns == db["columns"], "reference SQL columns differ from stored columns")
        if db["order_matters"]:
            require(rows == db["rows"], "database rows differ from read-only query")
        else:
            require(Counter(map(tuple, rows)) == Counter(map(tuple, db["rows"])), "database rows differ from read-only query")
        live_rows = [dict(zip(columns, row)) for row in rows]
    else:
        require(db is None and not record["expected_calculations"], "document case unexpectedly needs DB/calculator")
    validate_calculations(record, ctx, live_rows)
    judges = record["llm_judge_questions"]
    required = CRITERIA | ({"source_attribution", "unsupported_financial_claims"} if hybrid else set())
    require(len(judges) == len(required), "incorrect number of judge criteria")
    actual = set()
    for judge in judges:
        require(isinstance(judge, dict) and set(judge) == {"criterion_id", "stage", "question", "required_inputs", "scoring_anchors"}, "invalid judge entry")
        cid = judge["criterion_id"]
        require(cid in required and cid not in actual, "unknown/duplicate judge criterion")
        actual.add(cid)
        require(judge["stage"] == ("retrieval" if cid in {"evidence_coverage", "context_relevance"} else "generation"), f"{cid}: incorrect stage")
        require(nonempty(judge["question"]) and qid in judge["question"], f"{cid}: missing case-specific judge question")
        strings(judge["required_inputs"], f"{cid}.required_inputs")
        require(set(judge["required_inputs"]) <= set(FIELDS) | RUNTIME_INPUTS, f"{cid}: unknown required input")
        score = judge["scoring_anchors"]
        require(isinstance(score, dict) and {"0", "1", "2"} <= set(score) <= {"0", "1", "2", "not_applicable"}, f"{cid}: invalid scoring anchors")
        require(all(nonempty(s) for s in score.values()), f"{cid}: empty scoring anchor")
        if cid == "faithfulness":
            require(not (set(judge["required_inputs"]) & {"expected_answer", "required_answer_facts", "required_document_evidence", "expected_database_response", "expected_calculations"}), "faithfulness must not use hidden gold to justify claims")
    require(actual == required, "missing judge criteria")


def load_records(path):
    records, errors = [], []
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            try:
                require(bool(line.strip()), "blank JSONL line")
                records.append(strict_json(line))
            except (ValueError, TypeError) as error:
                errors.append(f"line {line_number}: {error}")
    return records, errors


def validate_dataset(records, ctx):
    errors, seen = [], set()
    for index, record in enumerate(records, 1):
        qid = record.get("question_id", f"line {index}") if isinstance(record, dict) else f"line {index}"
        try:
            require(isinstance(qid, str), "question_id must be a string")
            require(qid not in seen, "duplicate question_id")
            seen.add(qid)
            validate_record(record, ctx)
        except (ValueError, TypeError, KeyError, sqlite3.Error, ArithmeticError) as error:
            errors.append(f"{qid}: {error}")
    if seen != set(ctx.questions):
        errors.append(f"question coverage: missing {sorted(set(ctx.questions)-seen)}; unexpected {sorted(seen-set(ctx.questions))}")
    counts = Counter(r.get("difficulty") for r in records if isinstance(r, dict) and isinstance(r.get("difficulty"), str))
    if len(records) != 48 or counts != {"easy": 16, "medium": 16, "hard": 16}:
        errors.append(f"expected 48 records / 16 per difficulty; found {len(records)} / {dict(counts)}")
    return errors


def self_check(records, ctx, manifest):
    """Exercise negative fixtures in memory; never edit the benchmark or sources."""
    tests = []

    def rejected(label, callback):
        try:
            callback()
        except (ValueError, TypeError, KeyError, sqlite3.Error, ArithmeticError):
            tests.append(label)
            return
        raise InvalidBenchmark(f"self-check failed to reject {label}")

    def changed(qid, mutate):
        record = copy.deepcopy(next(r for r in records if r["question_id"] == qid))
        mutate(record)
        validate_record(record, ctx)

    rejected("malformed JSON", lambda: strict_json('{"question_id":'))
    rejected("duplicate JSON key", lambda: strict_json('{"x":1,"x":2}'))
    rejected("non-finite JSON number", lambda: strict_json('{"x":NaN}'))
    rejected("missing field", lambda: changed("E01", lambda r: r.pop("question")))
    rejected("incorrect flag type", lambda: changed("E01", lambda r: r.update(is_document_1_needed="true")))
    rejected("source flag mismatch", lambda: changed("E01", lambda r: r.update(is_document_2_needed=True)))
    rejected("altered evidence", lambda: changed("E01", lambda r: r["required_document_evidence"][0]["alternatives"][0].update(text="Annual plans have a fabricated 99% discount.")))
    rejected("wrong PDF page", lambda: changed("E01", lambda r: r["required_document_evidence"][0]["alternatives"][0].update(page=4)))
    rejected("incorrect database rows", lambda: changed("X-M01", lambda r: r["expected_database_response"]["rows"][0].__setitem__(7, 9999)))
    rejected("dangerous SQL", lambda: changed("X-M01", lambda r: r["expected_database_response"].update(reference_sql="DELETE FROM customers")))
    rejected("SQL write hidden in WITH", lambda: ctx.query("WITH chosen AS (SELECT 1) DELETE FROM customers", {}))
    rejected("incorrect calculation", lambda: changed("X-M01", lambda r: r["expected_calculations"][0]["expected_results"].update(credit_amount="9999.00")))
    rejected("incorrect bracket", lambda: changed("X-M01", lambda r: r["expected_calculations"][0]["expected_results"].update(credit_percentage=10)))
    rejected("fabricated calculation input", lambda: changed("X-M01", lambda r: r["expected_calculations"][0]["inputs"].update(monthly_rate=9999)))
    rejected("incorrect total", lambda: changed("X-H01", lambda r: r["expected_calculations"][-1].update(expected_result="9999.00")))
    rejected("incorrect deadline", lambda: changed("X-H04", lambda r: r["expected_calculations"][-1].update(expected_result=30)))
    altered_manifest = copy.deepcopy(manifest)
    altered_manifest["sources"]["database"]["sha256"] = "0" * 64
    rejected("source snapshot drift", lambda: check_sources(altered_manifest))
    duplicate_errors = validate_dataset(records + [records[0]], ctx)
    require(any("duplicate question_id" in e for e in duplicate_errors), "self-check: duplicate ID accepted")
    tests.append("duplicate question ID")
    require(validate_dataset(records[:-1], ctx), "self-check: missing question accepted")
    tests.append("missing question")
    # Equivalent formatting and SQL must remain valid, rather than exact-string matches.
    equivalent = copy.deepcopy(next(r for r in records if r["question_id"] == "X-M01"))
    span = equivalent["required_document_evidence"][0]["alternatives"][0]
    span["text"] = " \n ".join(span["text"].split())
    # A fresh ID avoids redefining the canonical catalog entry during this fixture.
    span["evidence_id"] += ".whitespace-fixture"
    equivalent["expected_database_response"]["reference_sql"] += "\n-- equivalent SELECT"
    validate_record(equivalent, ctx)
    tests.append("valid whitespace and SQL alternative accepted")
    check_sources(manifest)
    return tests


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=HERE / "benchmark.jsonl")
    parser.add_argument("--self-check", action="store_true", help="also exercise in-memory valid/corrupt fixtures")
    args = parser.parse_args()
    ctx = None
    try:
        manifest = strict_json((HERE / "source_manifest.json").read_text(encoding="utf-8"))
        check_sources(manifest)
        ctx = SourceContext(manifest)
        records, errors = load_records(args.dataset)
        errors.extend(validate_dataset(records, ctx))
        if errors:
            for error in errors:
                print(f"FAIL {error}", file=sys.stderr)
            return 1
        if args.self_check:
            tests = self_check(records, ctx, manifest)
            print(f"PASS {len(tests)} validator self-checks")
        print(f"PASS {len(records)} records: 16 easy, 16 medium, 16 hard; "
              f"{sum(r['is_database_needed'] for r in records)} database cases; "
              f"{sum(r['is_calculator_needed'] for r in records)} calculator cases")
        print("PASS source hashes, original questions, PDF evidence, read-only SQL results, calculations, and judge rubrics")
        return 0
    except (OSError, ValueError, TypeError, KeyError, sqlite3.Error, subprocess.SubprocessError, ArithmeticError) as error:
        print(f"FAIL {error}", file=sys.stderr)
        return 1
    finally:
        if ctx is not None:
            ctx.close()


if __name__ == "__main__":
    sys.exit(main())
