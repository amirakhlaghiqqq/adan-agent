"""Collect real Compose API runs and assess saved traces against the eval datasets."""

import argparse
import asyncio
import hashlib
import json
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adan.schemas import QueryResponse  # noqa: E402


def save_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def cases():
    return [
        (suite, json.loads(line))
        for suite in ("rag", "coordinator")
        for line in (ROOT / "evals" / suite / "benchmark.jsonl").read_text().splitlines()
        if line.strip()
    ]


async def collect(args):
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=180, trust_env=False) as client:
        health = await client.get(args.base_url + "/health")
        health.raise_for_status()
        manifest = {
            "started_at": datetime.now(UTC).isoformat(),
            "base_url": args.base_url,
            "health": health.json(),
            "concurrency": args.concurrency,
            "trials": 1,
            "timeout_seconds": 180,
            "datasets": {},
        }
        for suite in ("rag", "coordinator"):
            source = ROOT / "evals" / suite / "benchmark.jsonl"
            manifest["datasets"][suite] = hashlib.sha256(source.read_bytes()).hexdigest()
            target = args.output / "datasets" / f"{suite}.jsonl"
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and target.read_bytes() != source.read_bytes():
                raise ValueError("Dataset changed: choose a new output directory")
            target.write_bytes(source.read_bytes())
        if not (args.output / "collection.json").exists():
            save_json(args.output / "collection.json", manifest)

        async def worker(suite, case):
            qid = case["question_id"]
            path = args.output / "runs" / suite / f"{qid}.json"
            payload = {key: case[key] for key in ("question", "input_context")}
            if path.exists():
                previous = json.loads(path.read_text())
                if previous["request"] != payload:
                    raise ValueError(f"Saved input differs for {suite}/{qid}")
                return
            async with semaphore:
                start = time.monotonic()
                record = {
                    "suite": suite,
                    "question_id": qid,
                    "request": payload,
                    "started_at": datetime.now(UTC).isoformat(),
                    "response": None,
                    "http_status": None,
                    "error": None,
                }
                try:
                    result = await client.post(args.base_url + "/api/v1/query", json=payload)
                    record["http_status"] = result.status_code
                    result.raise_for_status()
                    record["response"] = result.json()
                    QueryResponse.model_validate(record["response"])
                except Exception as exc:
                    # HTTP/provider error bodies can contain secrets; record type/status only.
                    record["error"] = type(exc).__name__
                record["wall_ms"] = round((time.monotonic() - start) * 1000, 3)
                save_json(path, record)
                response = record["response"] or {}
                print(
                    json.dumps(
                        {
                            "suite": suite,
                            "question_id": qid,
                            "status": response.get("status"),
                            "stop_reason": response.get("stop_reason"),
                            "error": record["error"],
                            "wall_ms": record["wall_ms"],
                        }
                    ),
                    flush=True,
                )
                await asyncio.sleep(args.pause_seconds)

        selected = [
            (suite, case)
            for suite, case in cases()
            if not args.only or f"{suite}:{case['question_id']}" in args.only
        ]
        await asyncio.gather(*(worker(suite, case) for suite, case in selected))


async def assess(args):
    from adan.config import Settings
    from evals.agent_assessment import (
        annotations_for,
        base_assessment,
        snapshot_corpus,
        write_reports,
    )
    from evals.agent_judge import Judge, semantic_assessment

    settings = Settings()
    model = args.judge_model or settings.text_model
    collection = json.loads((args.output / "collection.json").read_text())
    async with httpx.AsyncClient(timeout=30, trust_env=False) as local:
        corpus = await snapshot_corpus(
            local, args.output, args.qdrant_url, collection["health"]["index_fingerprint"]
        )
    save_json(args.output / "corpus.json", corpus)
    all_cases = cases()
    annotations = annotations_for(corpus, [case for suite, case in all_cases if suite == "rag"])
    save_json(args.output / "retrieval_annotations.json", annotations)
    metadata = {
        "judge_model": model,
        "judge_temperature": 0,
        "judge_max_attempts": 3,
        "judge_timeout_seconds": 90,
        "agent_trials_per_question": 1,
        "judge_is_same_model_as_generator": model == settings.text_model,
        "git_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        "source_sha256": {
            str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / "src").rglob("*.py"))
        },
        "corpus_chunks": len(corpus),
    }
    save_json(args.output / "assessment_config.json", metadata)
    proxy = None
    try:
        with socket.create_connection(("127.0.0.1", 10808), timeout=1):
            proxy = "http://127.0.0.1:10808"
    except OSError:
        pass
    assessments = []
    case_semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=90, proxy=proxy, trust_env=False) as remote:
        judge = Judge(remote, settings, model, args.output, asyncio.Semaphore(2), save_json)

        async def worker(suite, case):
            qid = case["question_id"]
            path = args.output / "runs" / suite / f"{qid}.json"
            if not path.exists() or args.only and f"{suite}:{qid}" not in args.only:
                return
            async with case_semaphore:
                record = json.loads(path.read_text())
                row, details = base_assessment(suite, case, record, annotations)
                row["response_file"] = str(path.relative_to(args.output))
                if suite == "rag" and record.get("response") and not record.get("error"):
                    await semantic_assessment(judge, case, record["response"], row, details, ROOT)
                assessment = {"row": row, "details": details}
                save_json(args.output / "assessments" / suite / f"{qid}.json", assessment)
                assessments.append(assessment)
                write_reports(
                    args.output,
                    sorted(assessments, key=lambda a: (a["row"]["suite"], a["row"]["question_id"])),
                )
                print(
                    json.dumps(
                        {
                            "assessed": f"{suite}/{qid}",
                            "generation": row["generate_score"],
                            "judge_errors": details["judge_errors"],
                        }
                    ),
                    flush=True,
                )

        await asyncio.gather(*(worker(suite, case) for suite, case in all_cases))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--concurrency", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--phase", choices=("collect", "assess", "all"), default="all")
    parser.add_argument("--judge-model")
    parser.add_argument("--qdrant-url", default="http://127.0.0.1:6333")
    parser.add_argument("--pause-seconds", type=float, default=3)
    args = parser.parse_args()
    if args.phase in ("collect", "all"):
        asyncio.run(collect(args))
    if args.phase in ("assess", "all"):
        asyncio.run(assess(args))


if __name__ == "__main__":
    main()
