import asyncio
import json

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
        from llama_index.embeddings.fastembed import FastEmbedEmbedding

        from adan.rag.index import PolicyIndex

        embed = FastEmbedEmbedding(
            model_name=settings.embedding_model,
            cache_dir=str(settings.embedding_cache_path),
            threads=2,
        )
        documents = PolicyIndex(
            settings.documents_path,
            settings.index_path,
            embed_model=embed,
            top_k=settings.top_k,
            url=settings.qdrant_url,
        )
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
                        "Rewrite into 1 or 2 focused policy search strings. "
                        "Preserve constraints. Return queries."
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
                chunks.extend(found)
        finally:
            if chunks:
                artifact = self.aggregator.build(run.question, run.input_context, chunks)
                run.aggregation_artifacts.append(artifact)
                run.chunks.extend(artifact["chunks"])
        if not chunks:
            artifact = self.aggregator.build(run.question, run.input_context, [])
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
