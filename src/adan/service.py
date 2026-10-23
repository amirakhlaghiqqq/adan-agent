import asyncio
import json
from copy import deepcopy

from adan.config import Settings
from adan.database import Database, ensure_database
from adan.models import OpenRouterModels
from adan.rag.aggregation import PassthroughAggregator
from adan.runtime import LimitReached, Run
from adan.schemas import QueryRequest, SearchPlan, SQLRequest, SQLStatement


class Assistant:
    def __init__(self, settings: Settings, *, models, documents, database, aggregator=None):
        self.settings, self.models = settings, models
        self.documents, self.database = documents, database
        self.aggregator = aggregator or PassthroughAggregator()
        from adan.agent import build_graph

        self.graph = build_graph()

    @classmethod
    def from_settings(cls, settings=None):
        settings = settings or Settings()
        models = OpenRouterModels(settings)
        ensure_database(settings.database_path)
        from adan.rag.config import RAGConfig
        from adan.rag.pipeline import RAGPipeline

        config = RAGConfig(
            openrouter_api_key=settings.openrouter_api_key.get_secret_value(),
            openrouter_base_url=settings.openrouter_base_url,
            openrouter_embedding_model=settings.openrouter_embedding_model,
            openrouter_reranker_model=settings.openrouter_reranker_model,
            generation_model=settings.text_model,
            qdrant_url=settings.qdrant_url,
            qdrant_api_key=settings.qdrant_api_key.get_secret_value(),
            qdrant_collection_name=settings.qdrant_collection_name,
            qdrant_local_path=settings.qdrant_local_path,
            documents_path=settings.documents_path,
            top_k=settings.retrieval_candidates,
            rerank_top_n=settings.top_k,
            enable_reranker=settings.enable_reranker,
        )
        config.validate()
        documents = RAGPipeline(config)
        try:
            documents.get_index()
        except Exception:
            documents.close()
            raise
        return cls(
            settings, models=models, documents=documents, database=Database(settings.database_path)
        )

    async def search_documents(self, query, run, *, parent_id=None):
        plan = await run.model(
            "rewrite",
            [
                {
                    "role": "system",
                    "content": (
                        "Rewrite into focused policy search strings (at most 3). "
                        "Preserve constraints and key entities. Return queries.\n"
                        "Corpus Topics & Keywords for Reference:\n"
                        "- Billing & Payment Policy: subscription cycles, "
                        "annual upfront discount (15%), "
                        "payment methods, Net-30 invoicing, operating currencies (USD, EUR, GBP), "
                        "delinquency escalation schedules, 30-day grace periods, "
                        "late payment interest (1.5%), "
                        "account suspension, 14-day refund cancellation windows, "
                        "non-refundable fees "
                        "(professional onboarding, compute usage, setup fees).\n"
                        "- SLA & Support Policy: service tiers (Starter 99.00%, "
                        "Professional 99.90%, Enterprise 99.99%), "
                        "monthly uptime percentage calculation formulas, "
                        "scheduled maintenance and third-party downtime exclusions, "
                        "service credit penalty tiers (10%, 25%, 50%), severity levels "
                        "(P1 Critical, P2 High, P3 Medium, P4 Low response targets), "
                        "support channels, official governance directories, "
                        "and 30-day credit claim filing deadlines."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"query": query, "input_context": run.input_context}),
                },
            ],
            schema=SearchPlan,
            parent_id=parent_id,
        )
        chunks = []
        seen_chunk_ids = set()
        try:
            for search in plan["queries"]:
                found = await run.execute(
                    "search_documents",
                    {"query": search},
                    lambda q=search: asyncio.to_thread(self.documents.search, q),
                    tool=True,
                    parent_id=parent_id,
                    kind="retrieval_calls",
                )
                for chunk in found[:5] if isinstance(found, list) else []:
                    cid = chunk.get("chunk_id")
                    if cid and cid not in seen_chunk_ids:
                        seen_chunk_ids.add(cid)
                        chunks.append(deepcopy(chunk))
                    elif not cid:
                        chunks.append(deepcopy(chunk))
        finally:
            if chunks:
                input_chunks = deepcopy(chunks)
                artifact = self.aggregator.build(run.question, run.input_context, chunks)
                artifact["input_chunks"] = input_chunks
                run.aggregation_artifacts.append(artifact)
                existing_ids = {c.get("chunk_id") for c in run.chunks}
                for c in artifact["chunks"]:
                    if c.get("chunk_id") not in existing_ids:
                        existing_ids.add(c.get("chunk_id"))
                        run.chunks.append(c)
        if not chunks:
            artifact = self.aggregator.build(run.question, run.input_context, [])
            artifact["input_chunks"] = []
            run.aggregation_artifacts.append(artifact)
        return artifact

    async def query_database(self, request, run, *, parent_id=None):
        request_data = {
            "request": request,
            "input_context": run.input_context,
            "schema": self.database.schema,
        }
        formulated = await run.model(
            "formulate",
            [
                {
                    "role": "system",
                    "content": "Formulate a precise read-only database request. "
                    "Preserve names, date windows and filters. "
                    "Do not calculate policy-derived results. "
                    "Do not authorize mutations. Return request.",
                },
                {"role": "user", "content": json.dumps(request_data)},
            ],
            schema=SQLRequest,
            parent_id=parent_id,
        )
        statement = await run.model(
            "sql",
            [
                {
                    "role": "system",
                    "content": "Generate exactly one read-only SQLite SELECT, "
                    "optionally with non-recursive CTEs. "
                    "Use named :parameters for values. Use only schema tables and columns. "
                    "No writes, schema inspection, file/extension functions or policy assumptions. "
                    "Return raw numerical fields, not formatted money. "
                    "Preserve period and customer filters. "
                    "Return sql and parameters. No markdown.",
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {**request_data, "formulated_request": formulated["request"]}
                    ),
                },
            ],
            schema=SQLStatement,
            parent_id=parent_id,
        )
        result = await run.execute(
            "query_database",
            statement,
            lambda: asyncio.to_thread(
                self.database.query,
                statement["sql"],
                statement["parameters"],
                timeout=min(10, run.remaining()),
            ),
            tool=True,
            parent_id=parent_id,
            kind="database_calls",
        )
        run.database_results.append(result)
        return result

    async def ask(self, question, input_context=None):
        request = QueryRequest(question=question, input_context=input_context or [])
        run = Run(self, request.question, request.input_context)
        try:
            state = await self.graph.ainvoke(
                request.model_dump(), context={"run": run}, config={"recursion_limit": 100}
            )
            return state["response"]
        except LimitReached as exc:
            run.stop_reason = str(exc)
        except Exception as exc:
            run.stop_reason = "application_error"
            run.failures.append({"stage": "application", "error_type": type(exc).__name__})
        from adan.utils.nodes import response

        return response({}, run)

    def close(self):
        if hasattr(self.documents, "close"):
            self.documents.close()
