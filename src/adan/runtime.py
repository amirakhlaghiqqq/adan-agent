"""Per-request budgets and append-only traces; never store credentials or hidden reasoning."""

import asyncio
import json
import logging
import time
from datetime import UTC, datetime
from uuid import uuid4

from langchain_core.messages import AIMessage
from openai import APIConnectionError, APIStatusError

from adan.database import UnsafeSQL

logger = logging.getLogger("adan")


class LimitReached(Exception):
    pass


def visible_message(message):
    if isinstance(message, dict):
        return message
    result = {
        "role": {"human": "user", "ai": "assistant"}.get(message.type, message.type),
        "content": message.content,
    }
    if isinstance(message, AIMessage) and message.tool_calls:
        result["tool_calls"] = message.tool_calls
    if hasattr(message, "tool_call_id"):
        result["tool_call_id"] = message.tool_call_id
    return result


class Run:
    def __init__(self, services, question, input_context):
        self.services, self.settings = services, services.settings
        self.question, self.input_context = question, input_context
        self.run_id = str(uuid4())
        self.deadline = time.monotonic() + self.settings.request_timeout_seconds
        self.lock = asyncio.Lock()
        self.counts = {"tools": 0, "document_followups": 0, "database_followups": 0, "turns": 0}
        self.trace, self.retrieval_calls, self.database_calls, self.tool_calls = [], [], [], []
        self.aggregation_artifacts, self.generator_contexts, self.guardrail_history = [], [], []
        self.chunks, self.database_results = [], []
        self.failures = []
        self.stop_reason = "completed"

    def remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise LimitReached("request_timeout")
        return remaining

    async def reserve(self, kind, limit, reason):
        async with self.lock:
            self.remaining()
            if self.counts[kind] >= limit:
                raise LimitReached(reason)
            self.counts[kind] += 1

    def event(self, name, inputs, parent_id=None):
        event = {
            "event_id": str(uuid4()),
            "run_id": self.run_id,
            "parent_id": parent_id,
            "dispatch_sequence": len(self.trace),
            "name": name,
            "inputs": inputs,
            "started_at": datetime.now(UTC).isoformat(),
            "status": "running",
        }
        self.trace.append(event)
        logger.info("run=%s step=%s name=%s", self.run_id, event["dispatch_sequence"], name)
        return event

    async def execute(self, name, inputs, function, *, tool=False, parent_id=None, kind=None):
        for attempt in range(self.settings.transient_retries + 1):
            if tool:
                await self.reserve("tools", self.settings.max_tool_calls, "max_tool_calls")
            event = self.event(name, inputs, parent_id)
            event["attempt"] = attempt + 1
            if kind:
                getattr(self, kind).append(event)
            if tool:
                self.tool_calls.append(event)
            start = time.monotonic()
            try:
                seconds = (
                    self.settings.tool_timeout_seconds
                    if tool
                    else self.settings.model_timeout_seconds
                )
                async with asyncio.timeout(min(seconds, self.remaining())):
                    output = await function()
                event.update(status="ok", output=output)
                return output
            except Exception as exc:
                blocked = isinstance(exc, UnsafeSQL)
                transient = isinstance(exc, (TimeoutError, APIConnectionError)) or (
                    isinstance(exc, APIStatusError)
                    and (exc.status_code == 429 or exc.status_code >= 500)
                )
                # Provider error bodies may contain request details. Expose type/status only.
                error = (
                    str(exc) if isinstance(exc, (ValueError, LimitReached)) else type(exc).__name__
                )
                event.update(
                    status="blocked" if blocked else "error",
                    output={
                        "error": error,
                        "error_type": type(exc).__name__,
                        "http_status": getattr(exc, "status_code", None),
                    },
                )
                if not transient or attempt >= self.settings.transient_retries:
                    raise
            finally:
                event["duration_ms"] = round((time.monotonic() - start) * 1000, 3)
                event["finished_at"] = datetime.now(UTC).isoformat()
        raise RuntimeError("Unreachable retry state")

    async def model(
        self, purpose, messages, *, schema=None, tools=None, parent_id=None, fallback=False
    ):
        async def call():
            result = await self.services.models.call(
                purpose, messages, schema=schema, tools=tools, fallback=fallback
            )
            output = {
                "message": visible_message(result),
                "usage": result.usage_metadata,
                "model": result.response_metadata.get("model_name"),
                "cost": result.response_metadata.get("cost"),
            }
            if schema:
                output["parsed"] = schema.model_validate_json(result.content).model_dump()
            else:
                output["ai_message"] = result
            return output

        output = await self.execute(
            "model." + purpose,
            {
                "messages": [visible_message(m) for m in messages],
                "schema": schema.__name__ if schema else None,
                "fallback": fallback,
                "model": (
                    self.settings.router_fallback_model if fallback else self.settings.router_model
                )
                if purpose == "coordinator"
                else self.settings.text_model,
            },
            call,
            parent_id=parent_id,
        )
        # The original message is needed for the graph, but is never serialized into public traces.
        if schema:
            return output["parsed"]
        return output.pop("ai_message")

    def evidence(self):
        return {
            "documents": self.chunks,
            "database_results": self.database_results,
            "tool_results": [
                {"name": c["name"], "status": c["status"], "output": c.get("output")}
                for c in self.tool_calls
                if c["name"] == "calculate"
            ],
            "acquisition_failures": self.failures,
        }

    def serialized_evidence(self):
        return json.dumps(self.evidence(), ensure_ascii=False)
