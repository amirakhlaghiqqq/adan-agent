"""Build the CSV from saved agent runs and user-requested parallel Luna judgments."""

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals.agent_assessment import (  # noqa: E402
    apply_execution_limits,
    base_assessment,
    write_reports,
)
from evals.agent_judge import semantic_assessment  # noqa: E402


class SavedLunaJudge:
    def __init__(self, output):
        self.output = output

    async def call(self, qid, stage, inputs, schema):
        job_path = self.output / "luna_jobs" / stage / f"{qid}.json"
        result_path = self.output / "luna_results" / stage / f"{qid}.json"
        job = json.loads(job_path.read_text())
        if job["inputs"] != inputs or job["schema"] != schema.model_json_schema():
            raise ValueError("Luna result inputs/schema differ from the saved assessment job")
        result = schema.model_validate_json(result_path.read_text())
        record = {
            "backend": "luna_subagents",
            "model": "gpt-6-luna",
            "job_sha256": hashlib.sha256(job_path.read_bytes()).hexdigest(),
            "request": job,
            "result": result.model_dump(),
            "cost": None,
        }
        path = self.output / "luna_judges" / qid / f"{stage}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        return result


async def assemble(output):
    selection = json.loads((output / "selection.json").read_text())
    cases = {
        (suite, case["question_id"]): case
        for suite in ("rag", "coordinator")
        for case in [
            json.loads(line)
            for line in (output / "datasets" / f"{suite}.jsonl").read_text().splitlines()
        ]
    }
    annotations = json.loads((output / "retrieval_annotations.json").read_text())
    judge, assessments = SavedLunaJudge(output), []
    metadata_path = output / "assessment_config.json"
    metadata = json.loads(metadata_path.read_text())
    for key in ("judge_max_attempts", "judge_timeout_seconds"):
        metadata.pop(key, None)
    metadata.update(
        {
            "judge_backend": "luna_subagents",
            "judge_model": "gpt-6-luna",
            "parallel_workers": 3,
            "judge_max_concurrency": 3,
            "judge_jobs": 26,
            "cost": None,
            "judge_is_same_model_as_generator": False,
            "excluded_judges": "Earlier Nemotron and Antigravity attempts are audit-only, excluded",
        }
    )
    metadata["evaluator_sha256"] = {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (
            ROOT / "scripts/evaluate_agent.py",
            Path(__file__).resolve(),
            ROOT / "evals/agent_assessment.py",
            ROOT / "evals/agent_judge.py",
            ROOT / "evals/rag/retrieval_judgments.py",
            ROOT / "evals/rag/retrieval_metrics.py",
        )
    }
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    for selected in selection["cases"]:
        suite, qid = selected["suite"], selected["question_id"]
        case = cases[suite, qid]
        path = output / "runs" / suite / f"{qid}.json"
        record = json.loads(path.read_text())
        row, details = base_assessment(suite, case, record, annotations)
        row["response_file"] = str(path.relative_to(output))
        row["judge_model"] = "gpt-6-luna" if suite == "rag" else ""
        if suite == "rag" and record.get("response") and not record.get("error"):
            await semantic_assessment(judge, case, record["response"], row, details, ROOT)
        if record.get("response") and not record.get("error"):
            apply_execution_limits(row, details, record["response"], case)
        assessment = {"row": row, "details": details}
        target = output / "assessments" / suite / f"{qid}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(assessment, ensure_ascii=False, indent=2) + "\n")
        assessments.append(assessment)
    write_reports(output, assessments)
    errors = [
        (a["row"]["question_id"], a["details"]["judge_errors"])
        for a in assessments
        if a["details"]["judge_errors"]
    ]
    if errors:
        raise ValueError(f"Incomplete Luna assessments: {errors}")
    print(f"Saved {len(assessments)} rows; all Luna judgments validated.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(assemble(parser.parse_args().output))
