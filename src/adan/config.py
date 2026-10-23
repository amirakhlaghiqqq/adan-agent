from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openrouter_api_key: SecretStr = SecretStr("")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    router_model: str = "baseten/mammoth-1:free"
    router_fallback_model: str = "nvidia/nemotron-3.5-lightning:free"
    text_model: str = "nvidia/nemotron-3.5-lightning:free"
    database_path: Path = Path("data/database/app.db")
    documents_path: Path = Path("data/documents")
    openrouter_embedding_model: str = "nvidia/nemotron-3-embed-1b:free"
    openrouter_reranker_model: str = "nvidia/llama-nemotron-rerank-vl-1b-v2:free"
    enable_reranker: bool = False
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: SecretStr = SecretStr("")
    qdrant_collection_name: str = "enterprise_policies"
    qdrant_local_path: Path = Path(".cache/adan/qdrant_hybrid")
    top_k: int = Field(5, ge=1, le=20)
    retrieval_candidates: int = Field(20, ge=1, le=100)
    request_timeout_seconds: float = Field(120, gt=0)
    model_timeout_seconds: float = Field(30, gt=0)
    tool_timeout_seconds: float = Field(20, gt=0)
    max_tool_calls: int = Field(24, ge=0, le=100)
    max_generator_turns: int = Field(12, ge=1, le=30)
    max_document_followups: int = Field(2, ge=0, le=10)
    max_database_followups: int = Field(2, ge=0, le=10)
    max_corrections: int = Field(2, ge=0, le=5)
    transient_retries: int = Field(1, ge=0, le=2)
