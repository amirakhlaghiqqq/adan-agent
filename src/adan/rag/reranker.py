"""OpenRouter reranking with per-call, inspectable fallback outcomes."""

from __future__ import annotations

import asyncio
import math
import time
from typing import Any

import httpx
from llama_index.core.postprocessor.types import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle
from pydantic import Field


class OpenRouterRerank(BaseNodePostprocessor):
    api_key: str = Field(repr=False, exclude=True)
    base_url: str = "https://openrouter.ai/api/v1"
    model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
    top_n: int = Field(default=5, ge=1)
    timeout_seconds: float = 30.0

    @classmethod
    def class_name(cls) -> str:
        return "OpenRouterRerank"

    def _build_request_payload(self, nodes, query):
        return (
            f"{self.base_url.rstrip('/')}/rerank",
            {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            {
                "model": self.model,
                "query": query,
                "documents": [n.node.get_content() for n in nodes],
                "top_n": min(self.top_n, len(nodes)),
            },
        )

    def _process_response(self, data: dict[str, Any], nodes):
        results = data.get("results", [])
        if len(results) != min(self.top_n, len(nodes)):
            raise ValueError("Incomplete reranker response")
        seen, output = set(), []
        for item in results:
            idx, score = item.get("index"), float(item.get("relevance_score", float("nan")))
            if (
                type(idx) is not int
                or not 0 <= idx < len(nodes)
                or idx in seen
                or not math.isfinite(score)
            ):
                raise ValueError("Invalid reranker result")
            seen.add(idx)
            output.append(NodeWithScore(node=nodes[idx].node, score=score))
        return output

    def rerank_with_trace(self, nodes, query):
        start = time.perf_counter()
        endpoint, headers, payload = self._build_request_payload(nodes, query)
        trace = {
            "endpoint": endpoint,
            "request": payload,
            "attempts": [],
            "status": "skipped",
            "usage": None,
            "cost": None,
        }
        if not nodes or not query.strip():
            trace["latency_ms"] = 0.0
            return nodes[: self.top_n], trace
        for attempt in range(2):
            entry = {"attempt": attempt + 1}
            trace["attempts"].append(entry)
            try:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.post(endpoint, headers=headers, json=payload)
                entry["http_status"] = response.status_code
                response.raise_for_status()
                data = response.json()
                entry["response"] = data
                output = self._process_response(data, nodes)
                trace.update(
                    status="success",
                    usage=data.get("usage"),
                    cost=data.get("usage", {}).get("cost"),
                )
                break
            except Exception as exc:
                entry["error_type"] = type(exc).__name__
                status = entry.get("http_status", 0)
                transient = isinstance(exc, httpx.TransportError) or status in (429, 502, 503, 504)
                if attempt == 0 and transient:
                    time.sleep(1)
                    continue
                trace["status"] = "fallback"
                output = nodes[: self.top_n]
                break
        trace["latency_ms"] = (time.perf_counter() - start) * 1000
        return output, trace

    def _postprocess_nodes(self, nodes, query_bundle: QueryBundle | None = None):
        return self.rerank_with_trace(nodes, query_bundle.query_str if query_bundle else "")[0]

    async def _apostprocess_nodes(self, nodes, query_bundle: QueryBundle | None = None):
        return await asyncio.to_thread(self._postprocess_nodes, nodes, query_bundle)
