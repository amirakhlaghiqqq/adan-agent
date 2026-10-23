import importlib.util
import json
from pathlib import Path

import pytest
from conftest import final, tool

spec = importlib.util.spec_from_file_location(
    "smoke", Path(__file__).resolve().parents[2] / "scripts" / "smoke.py"
)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_live_check_rejects_currency_labels_without_a_database_currency():
    response = {
        "stop_reason": "completed",
        "status": "complete",
        "answer": (
            "Aegis Financial Systems: Enterprise Financial Cloud plan, $4800.0. "
            "Apex Global Technologies: Enterprise Platform Suite, $4800.0. "
            "Nexus Logistics Hub: Enterprise Global Logistics, $4200.0."
        ),
        "citations": [],
        "retrieval_calls": [],
        "database_calls": [{"status": "ok", "output": {"rows": [["raw result"]]}}],
    }

    with pytest.raises(AssertionError, match="unsupported currency label"):
        smoke.check_evidence("database", response)


async def test_local_smoke_initializes_api_and_saves_actual_tool_response(
    make_assistant, monkeypatch, tmp_path
):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": True}],
            "formulate": [{"request": "Count all customers"}],
            "sql": [{"sql": "SELECT COUNT(*) AS n FROM customers", "parameters": {}}],
            "generate": [
                tool("calculate", {"operation": "evaluate", "expression": "30/2"}),
                final("There are 30 customers; half is 15."),
            ],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    monkeypatch.setattr(smoke.Assistant, "from_settings", lambda: assistant)
    output = tmp_path / "responses.json"
    monkeypatch.setattr(
        "sys.argv", ["smoke.py", "--scenario", "calculation", "--output", str(output)]
    )

    await smoke.main()

    response = json.loads(output.read_text())[0]["response"]
    assert response["database_results"][0]["rows"] == [[30]]
    assert response["calculator_trace"][0]["output"]["value"] == "15"
    assert response["status"] == "complete"
