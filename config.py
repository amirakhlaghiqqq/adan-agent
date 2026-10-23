"""Root configuration loader using python-dotenv for RAG ingestion and retrieval."""

from __future__ import annotations

from adan.rag.config import RAGConfig, load_config

__all__ = ["RAGConfig", "load_config"]

if __name__ == "__main__":
    cfg = load_config()
    masked_key = (
        f"{cfg.openrouter_api_key[:6]}...{cfg.openrouter_api_key[-4:]}"
        if len(cfg.openrouter_api_key) > 10
        else "***"
    )
    print("Loaded RAGConfig successfully:")
    print(f"  OPENROUTER_BASE_URL: {cfg.openrouter_base_url}")
    print(f"  OPENROUTER_API_KEY: {masked_key}")
    print(f"  OPENROUTER_EMBEDDING_MODEL: {cfg.openrouter_embedding_model}")
    print(f"  OPENROUTER_RERANKER_MODEL: {cfg.openrouter_reranker_model}")
    print(f"  QDRANT_URL: {cfg.qdrant_url or '(Local Embedded)'}")
    print(f"  QDRANT_LOCAL_PATH: {cfg.qdrant_local_path}")
    print(f"  QDRANT_COLLECTION_NAME: {cfg.qdrant_collection_name}")
    print(f"  IS_LOCAL_QDRANT: {cfg.is_local_qdrant}")
