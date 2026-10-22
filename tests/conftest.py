import json
from collections import defaultdict
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from adan.config import Settings
from adan.database import Database
from adan.service import Assistant


class ScriptedModels:
    """Deterministic transport double; real graph, tools, DB and API still execute."""

    def __init__(self, steps):
        self.steps = {key: list(value) for key, value in steps.items()}
        self.calls = defaultdict(list)

    async def call(self, purpose, messages, *, tools=None, schema=None, fallback=False):
        self.calls[purpose].append(messages)
        value = self.steps[purpose].pop(0)
        if isinstance(value, Exception):
            raise value
        return value if isinstance(value, AIMessage) else AIMessage(content=json.dumps(value))


class Documents:
    fingerprint = "test-index"

    def search(self, query):
        return [
            {
                "chunk_id": "billing-p1-s1",
                "document_id": "DOC-BIL-2024-V3",
                "source_file": "enterprise_billing_and_refund_policy.pdf",
                "page_number": 1,
                "section": "1. Billing",
                "text": "Reference policy text for this test.",
                "score": 0.9,
            }
        ]


def tool(name, arguments, call_id="call-1"):
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": arguments}])


def final(answer="There are 30 customers.", citations=None, status="complete"):
    return tool(
        "submit_answer",
        {
            "answer": answer,
            "citation_ids": citations or [],
            "status": status,
            "missing_information": [],
        },
        "final",
    )


@pytest.fixture
def make_assistant():
    def make(steps, **settings):
        models = ScriptedModels(steps)
        assistant = Assistant(
            Settings(_env_file=None, **settings),
            models=models,
            documents=Documents(),
            database=Database(Path("data/database/app.db")),
        )
        return assistant, models

    return make
