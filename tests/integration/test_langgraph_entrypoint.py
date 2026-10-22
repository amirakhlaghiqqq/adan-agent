import json
from types import SimpleNamespace

from conftest import final

from adan.agent import build_graph


async def test_studio_factory_can_be_inspected_without_loading_models(monkeypatch):
    from adan.agent import make_graph

    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    graph = await make_graph(SimpleNamespace(execution_runtime=None))
    assert "coordinator" in graph.get_graph().nodes
    assert "question" in graph.get_input_jsonschema()["properties"]
    json.dumps(graph.get_output_jsonschema())
    json.dumps(graph.get_context_jsonschema())


async def test_server_graph_uses_same_application_without_nonserializable_inputs(make_assistant):
    assistant, _ = make_assistant(
        {
            "coordinator": [{"needs_docs": False, "needs_db": False}],
            "generate": [final("I can help with CloudScale.")],
            "guard": [{"passed": True, "feedback": ""}],
        }
    )
    graph = build_graph(services=assistant, external=True)
    result = await graph.ainvoke({"question": "Hello", "input_context": []})
    assert result["response"]["status"] == "complete"
    assert set(result) == {"response"}
    json.dumps(result, default=str)
