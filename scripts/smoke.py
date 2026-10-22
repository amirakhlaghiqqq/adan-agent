"""Small live API smoke run. No benchmark files, scoring, or credentials are written."""

import argparse
import asyncio
import json
import logging
from pathlib import Path

import httpx

from adan.api import create_app
from adan.service import Assistant

SCENARIOS = {
    "documents": ("Which payment methods does CloudScale accept? Cite the policy.", []),
    "database": (
        "List the three companies with the highest subscription monthly_rate, "
        "including their plan names and raw rates.",
        [],
    ),
    "calculation": (
        "How many customers are there in the database, and what is half that count?",
        [],
    ),
    "hybrid": (
        "For customer 1, explain which support tier applies and show their stored "
        "subscription plan and billing cycle. Cite the relevant support policy.",
        [],
    ),
}


def check_evidence(name, data):
    assert data["status"] == "complete", f"{name}: answer did not complete"
    assert data["stop_reason"] == "completed", f"{name}: {data['stop_reason']}"
    if name in ("documents", "hybrid"):
        assert data["citations"], f"{name}: missing citations"
        assert any(c["status"] == "ok" and c["output"] for c in data["retrieval_calls"])
    if name in ("database", "calculation", "hybrid"):
        assert any(c["status"] == "ok" and c["output"]["rows"] for c in data["database_calls"])
    if name == "calculation":
        assert any(c["name"] == "calculate" and c["status"] == "ok" for c in data["tool_calls"])


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    parser.add_argument("--output", type=Path, help="Optional sanitized response artifact path")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    assistant = await asyncio.to_thread(Assistant.from_settings)
    app = create_app(assistant)
    results = []
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://adan"
            ) as client:
                assert (await client.get("/health")).status_code == 200
                for name, (question, context) in SCENARIOS.items():
                    if args.scenario not in ("all", name):
                        continue
                    result = await client.post(
                        "/api/v1/query", json={"question": question, "input_context": context}
                    )
                    result.raise_for_status()
                    data = result.json()
                    results.append({"scenario": name, "response": data})
                    print(
                        json.dumps(
                            {
                                "scenario": name,
                                "status": data["status"],
                                "stop_reason": data["stop_reason"],
                                "route": data["route"],
                                "answer": data["answer"],
                                "tools": len(data["tool_calls"]),
                            },
                            ensure_ascii=False,
                        ),
                        flush=True,
                    )
    finally:
        assistant.close()
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2), encoding="utf-8")
    for result in results:
        check_evidence(result["scenario"], result["response"])


if __name__ == "__main__":
    asyncio.run(main())
