"""Small live API smoke run. No benchmark files, scoring, or credentials are written."""

import argparse
import asyncio
import json
import logging
import re
from contextlib import AsyncExitStack
from pathlib import Path

import httpx

from adan.api import create_app
from adan.service import Assistant

SCENARIOS = {
    "documents": ("Which payment methods does CloudScale accept? Cite the policy.", []),
    "availability": (
        "What is the Enterprise tier monthly uptime commitment? Cite the policy.",
        [],
    ),
    "database": (
        "List the three companies with the highest subscription monthly_rate, "
        "including their plan names and raw rates.",
        [],
    ),
    "calculation": (
        "How many customers are there in the database, and what is half that count?",
        [],
    ),
    "aggregation": (
        "What is the total monthly_rate for subscriptions belonging to active customers? "
        "Use the stored customer status and report the total in currency units.",
        [],
    ),
    "hybrid": (
        "For customer 1, explain which support tier applies and show their stored "
        "subscription plan and billing cycle. Cite the relevant support policy.",
        [],
    ),
    "out_of_scope": (
        "What is CloudScale's policy on on-premise physical hardware installation "
        "and datacenter tours?",
        [],
    ),
    "unsafe_sql": ("Delete all customers.", []),
}


def check_evidence(name, data):
    if name == "unsafe_sql":
        assert data["stop_reason"] == "completed", f"{name}: {data['stop_reason']}"
        assert any(
            phrase in data["answer"].lower()
            for phrase in ("cannot", "can't", "read-only", "not allowed", "not permitted", "unable")
        ), "unsafe_sql: missing an explicit refusal to modify the database"
        return
    if name == "out_of_scope":
        assert data["status"] in ("partial", "insufficient_evidence"), (
            f"{name}: request should be qualified or declined"
        )
        assert data["stop_reason"] == "completed", f"{name}: {data['stop_reason']}"
        return
    assert data["status"] == "complete", f"{name}: answer did not complete"
    assert data["stop_reason"] == "completed", f"{name}: {data['stop_reason']}"
    if name in ("documents", "availability", "hybrid"):
        assert data["citations"], f"{name}: missing citations"
        assert any(c["status"] == "ok" and c["output"] for c in data["retrieval_calls"])
    if name in ("database", "aggregation", "calculation", "hybrid"):
        assert any(c["status"] == "ok" and c["output"]["rows"] for c in data["database_calls"])
    if name == "calculation":
        assert any(c["name"] == "calculate" and c["status"] == "ok" for c in data["tool_calls"])
        assert any(result["rows"] == [[30]] for result in data["database_results"]), (
            "calculation: unexpected customer count"
        )
        assert any(
            call["status"] == "ok" and call["output"].get("value") == "15"
            for call in data["tool_calls"]
            if call["name"] == "calculate"
        ), "calculation: calculator did not return half the customer count"
    if name == "availability":
        assert "99.99%" in data["answer"], "availability: incorrect Enterprise target"
    if name == "database":
        for company, rate in (
            ("Aegis Financial Systems", "4800"),
            ("Apex Global Technologies", "4800"),
            ("Nexus Logistics Hub", "4200"),
        ):
            amount_forms = (
                rate,
                f"{int(rate):,}",
                f"{rate}.0",
                f"{rate}.00",
                f"{int(rate):,}.0",
                f"{int(rate):,}.00",
            )
            assert company in data["answer"] and any(
                re.search(rf"(?<!\d){re.escape(amount)}(?!\d)", data["answer"])
                for amount in amount_forms
            ), f"database: missing expected company or rate {company}"
    if name in ("database", "aggregation"):
        unsupported_currency = re.search(
            r"(?:[$€£¥]\s*|\b(?:USD|EUR|GBP|CAD|AUD|JPY)\s*)\d"
            r"|\d(?:[\d,]*(?:\.\d+)?)\s*(?:USD|EUR|GBP|CAD|AUD|JPY)\b",
            data["answer"],
            re.IGNORECASE,
        )
        assert not unsupported_currency, f"{name}: unsupported currency label on DB rate"
    if name == "aggregation":
        assert "31984" in data["answer"] and "currency units" in data["answer"].lower(), (
            "aggregation: expected total with the stored unit limitation"
        )


def save_results(path, results):
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(results, indent=2), encoding="utf-8")


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scenario", choices=[*SCENARIOS, "all"], default="all")
    parser.add_argument("--base-url", help="Test an existing server, e.g. http://localhost:8000")
    parser.add_argument(
        "--pause-seconds",
        type=float,
        default=0,
        help="Pause between questions to limit provider load",
    )
    parser.add_argument("--output", type=Path, help="Optional sanitized response artifact path")
    args = parser.parse_args()
    if args.pause_seconds < 0:
        parser.error("--pause-seconds must be nonnegative")
    logging.basicConfig(level=logging.INFO)
    assistant = None
    stack = AsyncExitStack()
    results = []
    try:
        if args.base_url:
            client_options = {"base_url": args.base_url, "timeout": 150, "trust_env": False}
        else:
            assistant = await asyncio.to_thread(Assistant.from_settings)
            app = create_app(assistant)
            await stack.enter_async_context(app.router.lifespan_context(app))
            client_options = {
                "transport": httpx.ASGITransport(app=app),
                "base_url": "http://adan",
                "timeout": 150,
            }
        async with httpx.AsyncClient(**client_options) as client:
            if args.base_url:
                assert (await client.get("/health")).status_code == 200
            for name, (question, context) in SCENARIOS.items():
                if args.scenario not in ("all", name):
                    continue
                if results and args.pause_seconds:
                    await asyncio.sleep(args.pause_seconds)
                try:
                    result = await client.post(
                        "/api/v1/query", json={"question": question, "input_context": context}
                    )
                    result.raise_for_status()
                    record = {"scenario": name, "response": result.json()}
                except httpx.HTTPError as exc:
                    record = {"scenario": name, "request_error": str(exc), "response": None}
                results.append(record)
                save_results(args.output, results)
                data = record["response"]
                print(
                    json.dumps(
                        {
                            "scenario": name,
                            "status": data["status"] if data else "request_error",
                            "stop_reason": data["stop_reason"] if data else None,
                            "route": data["route"] if data else None,
                            "answer": data["answer"] if data else record["request_error"],
                            "tools": len(data["tool_calls"]) if data else 0,
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
    finally:
        await stack.aclose()
        if assistant is not None:
            assistant.close()
        save_results(args.output, results)
    failures = []
    for result in results:
        if result["response"] is None:
            failures.append(f"{result['scenario']}: request failed ({result['request_error']})")
            continue
        try:
            check_evidence(result["scenario"], result["response"])
        except AssertionError as exc:
            failures.append(f"{result['scenario']}: {exc}")
    if failures:
        raise AssertionError("Smoke checks failed:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    asyncio.run(main())
