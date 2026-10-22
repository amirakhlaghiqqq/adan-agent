import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from adan.schemas import QueryRequest, QueryResponse
from adan.service import Assistant


def create_app(assistant: Assistant | None = None):
    @asynccontextmanager
    async def lifespan(app):
        logging.basicConfig(
            level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
        )
        app.state.assistant = assistant or await asyncio.to_thread(Assistant.from_settings)
        yield
        if assistant is None:
            app.state.assistant.close()

    app = FastAPI(title="CloudScale Assistant", version="0.1.0", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok", "index_fingerprint": app.state.assistant.documents.fingerprint}

    @app.post("/api/v1/query", response_model=QueryResponse)
    async def query(request: QueryRequest):
        return await app.state.assistant.ask(request.question, request.input_context)

    return app


app = create_app()
