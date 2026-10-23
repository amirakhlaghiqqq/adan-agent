"""Qdrant Native Hybrid Store with OpenRouter Dense + FastEmbed BM25 Sparse."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import replace
from importlib.metadata import version
from typing import TYPE_CHECKING

from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.embeddings.openai_like import OpenAILikeEmbedding
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import AsyncQdrantClient, QdrantClient

if TYPE_CHECKING:
    from llama_index.core.schema import BaseNode

    from adan.rag.config import RAGConfig

logger = logging.getLogger(__name__)


def create_embed_model(config: RAGConfig) -> OpenAILikeEmbedding:
    """Create OpenAILikeEmbedding targeting OpenRouter."""
    return OpenAILikeEmbedding(
        model_name=config.openrouter_embedding_model,
        api_base=config.openrouter_base_url,
        api_key=config.openrouter_api_key,
        timeout=60.0,
        max_retries=2,
    )


def create_qdrant_client(config: RAGConfig) -> tuple[QdrantClient, AsyncQdrantClient | None]:
    """Initialize Qdrant client for local embedded or remote server deployment."""
    if config.is_local_qdrant:
        path_str = str(config.qdrant_local_path)
        if path_str != ":memory:":
            config.qdrant_local_path.mkdir(parents=True, exist_ok=True)
        logger.info("Initializing embedded local Qdrant at %s", path_str)
        client = QdrantClient(path=path_str)
        # Embedded local Qdrant uses an exclusive file lock and lacks async client
        return client, None

    logger.info("Connecting to remote Qdrant at %s", config.qdrant_url)
    api_key = config.qdrant_api_key or None
    client = QdrantClient(url=config.qdrant_url, api_key=api_key)
    aclient = AsyncQdrantClient(url=config.qdrant_url, api_key=api_key)
    return client, aclient


def create_hybrid_vector_store(
    config: RAGConfig,
    client: QdrantClient | None = None,
    aclient: AsyncQdrantClient | None = None,
) -> QdrantVectorStore:
    """Initialize QdrantVectorStore with hybrid search (dense + BM25 sparse)."""
    if client is None:
        client, aclient = create_qdrant_client(config)

    return QdrantVectorStore(
        client=client,
        aclient=aclient,
        collection_name=config.qdrant_collection_name,
        enable_hybrid=True,
        fastembed_sparse_model="Qdrant/bm25",
    )


class HybridIndexManager:
    """Manages index creation, ingestion, and retriever instantiation."""

    def __init__(self, config: RAGConfig):
        sources = {
            p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(config.documents_path.glob("*.pdf"))
        }
        if not sources:
            raise ValueError("No PDF sources available for index fingerprint")
        self.manifest = {
            "sources": sources,
            "chunking": "docling-markdown-pages-v4-formula",
            "embedding_model": config.openrouter_embedding_model,
            "embedding_base_url": config.openrouter_base_url,
            "sparse_model": "Qdrant/bm25",
            "versions": {
                p: version(p)
                for p in (
                    "docling",
                    "llama-index-core",
                    "llama-index-vector-stores-qdrant",
                    "fastembed",
                )
            },
        }
        encoded_manifest = json.dumps(self.manifest, sort_keys=True).encode()
        self.fingerprint = hashlib.sha256(encoded_manifest).hexdigest()
        config = replace(
            config,
            qdrant_collection_name=config.qdrant_collection_name + "_" + self.fingerprint[:16],
        )
        self.config = config
        self.client, self.aclient = create_qdrant_client(config)
        self.embed_model = create_embed_model(config)
        self.vector_store = create_hybrid_vector_store(
            config, client=self.client, aclient=self.aclient
        )

    def build_index(self, nodes: list[BaseNode]) -> VectorStoreIndex:
        """Build or update the hybrid index with nodes."""
        logger.info(
            "Building VectorStoreIndex for %d nodes into collection '%s'...",
            len(nodes),
            self.config.qdrant_collection_name,
        )
        for node in nodes:
            node.metadata["index_fingerprint"] = self.fingerprint
            if hasattr(node, "ref_doc_id") and not node.ref_doc_id:
                node.ref_doc_id = node.metadata.get("doc_id")
        storage_context = StorageContext.from_defaults(vector_store=self.vector_store)
        index = VectorStoreIndex(
            nodes=nodes,
            storage_context=storage_context,
            embed_model=self.embed_model,
        )
        return index

    def load_index(self) -> VectorStoreIndex:
        """Load an existing index from the vector store."""
        logger.info(
            "Loading existing VectorStoreIndex from collection '%s'...",
            self.config.qdrant_collection_name,
        )
        return VectorStoreIndex.from_vector_store(
            vector_store=self.vector_store,
            embed_model=self.embed_model,
        )

    def close(self) -> None:
        """Close client connections."""
        if self.aclient is not None:
            import asyncio

            try:
                asyncio.get_running_loop().create_task(self.aclient.close())
            except RuntimeError:
                asyncio.run(self.aclient.close())
        if hasattr(self.client, "close"):
            self.client.close()
