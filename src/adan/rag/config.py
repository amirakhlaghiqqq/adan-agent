"""Configuration loader using python-dotenv for RAG ingestion and retrieval."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class RAGConfig:
    openrouter_api_key: str
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_embedding_model: str = "nvidia/nemotron-3-embed-1b:free"
    openrouter_reranker_model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
    generation_model: str = "nvidia/nemotron-3.5-lightning:free"
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str = ""
    qdrant_collection_name: str = "enterprise_policies"
    qdrant_local_path: Path = Path(".cache/adan/qdrant_hybrid")
    documents_path: Path = Path("data/documents")
    top_k: int = 20
    rerank_top_n: int = 5
    enable_reranker: bool = False

    @property
    def is_local_qdrant(self) -> bool:
        """True if Qdrant should run in embedded local/in-memory mode."""
        if not self.qdrant_url:
            return True
        return not self.qdrant_url.startswith(("http://", "https://", "grpc://"))

    def validate(self) -> None:
        """Validate required environment configuration."""
        if not (1 <= self.top_k <= 100 and 1 <= self.rerank_top_n <= 100):
            raise ValueError("Retrieval limits must be between 1 and 100")
        if not self.openrouter_api_key or not self.openrouter_api_key.strip():
            raise ValueError(
                "OPENROUTER_API_KEY is required. Please set it in .env or the environment."
            )
        if not self.openrouter_embedding_model or not self.openrouter_embedding_model.strip():
            raise ValueError("OPENROUTER_EMBEDDING_MODEL must not be empty.")
        if not self.openrouter_reranker_model or not self.openrouter_reranker_model.strip():
            raise ValueError("OPENROUTER_RERANKER_MODEL must not be empty.")
        if not self.qdrant_collection_name or not self.qdrant_collection_name.strip():
            raise ValueError("QDRANT_COLLECTION_NAME must not be empty.")


def load_config(env_file: str | Path | None = None) -> RAGConfig:
    """Load and validate RAG configuration from .env file or environment variables."""
    if env_file:
        load_dotenv(dotenv_path=env_file, override=True)
    else:
        load_dotenv(override=False)

    config = RAGConfig(
        openrouter_api_key=os.getenv("OPENROUTER_API_KEY", "").strip(),
        openrouter_base_url=os.getenv(
            "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"
        ).strip(),
        openrouter_embedding_model=os.getenv(
            "OPENROUTER_EMBEDDING_MODEL", "nvidia/nemotron-3-embed-1b:free"
        ).strip(),
        openrouter_reranker_model=os.getenv(
            "OPENROUTER_RERANKER_MODEL", "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
        ).strip(),
        generation_model=os.getenv(
            "TEXT_MODEL",
            os.getenv("OPENROUTER_GENERATION_MODEL", "nvidia/nemotron-3.5-lightning:free"),
        ).strip(),
        qdrant_url=os.getenv("QDRANT_URL", "http://localhost:6333").strip(),
        qdrant_api_key=os.getenv("QDRANT_API_KEY", "").strip(),
        qdrant_collection_name=os.getenv("QDRANT_COLLECTION_NAME", "enterprise_policies").strip(),
        qdrant_local_path=Path(os.getenv("QDRANT_LOCAL_PATH", ".cache/adan/qdrant_hybrid")),
        documents_path=Path(os.getenv("DOCUMENTS_PATH", "data/documents")),
        top_k=int(os.getenv("RETRIEVAL_CANDIDATES", "20")),
        rerank_top_n=int(os.getenv("RERANK_TOP_N", os.getenv("TOP_K", "5"))),
        enable_reranker=os.getenv("ENABLE_RERANKER", "false").lower() in ("true", "1", "yes"),
    )
    config.validate()
    return config
