"""Unified RAG pipeline combining Docling parsing, MarkdownNodeParser, Hybrid Qdrant,
and OpenRouter Reranker.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import httpx
from llama_index.core import QueryBundle, VectorStoreIndex
from llama_index.core.schema import NodeWithScore

from adan.rag.config import RAGConfig, load_config
from adan.rag.docling_parser import DoclingPDFParser
from adan.rag.hybrid_store import HybridIndexManager
from adan.rag.node_parser import PolicyMarkdownNodeParser
from adan.rag.quality_control import ChunkQualityController, QualityControlReport
from adan.rag.reranker import OpenRouterRerank

logger = logging.getLogger(__name__)


class RAGPipeline:
    """Production-ready RAG ingestion and hybrid retrieval pipeline."""

    def __init__(self, config: RAGConfig | None = None):
        self.config = config or load_config()
        self.doc_parser = None
        self.qc_controller = ChunkQualityController()
        self.node_parser = PolicyMarkdownNodeParser(qc_controller=self.qc_controller)
        self.index_manager = HybridIndexManager(self.config)
        self.reranker = OpenRouterRerank(
            api_key=self.config.openrouter_api_key,
            base_url=self.config.openrouter_base_url,
            model=self.config.openrouter_reranker_model,
            top_n=self.config.rerank_top_n,
        )
        self._index: VectorStoreIndex | None = None

    def ingest_files(self, file_paths: list[str | Path]) -> VectorStoreIndex:
        """Parse PDF files with Docling, chunk with MarkdownNodeParser, and index in Qdrant."""
        if self.doc_parser is None:
            self.doc_parser = DoclingPDFParser(do_ocr=False, do_table_structure=True)
        all_documents = []
        for file_path in file_paths:
            doc = self.doc_parser.parse_file(file_path)
            all_documents.append(doc)

        nodes = self.node_parser.get_nodes_from_documents(all_documents)
        self._index = self.index_manager.build_index(nodes)
        return self._index

    def audit_collection(self) -> QualityControlReport:
        """Audit the active Qdrant collection for chunk quality and required fields."""
        return self.qc_controller.audit_qdrant_collection(
            self.index_manager.client,
            self.index_manager.config.qdrant_collection_name,
        )

    def ingest_directory(self, directory: str | Path = "data/documents") -> VectorStoreIndex:
        """Ingest all PDFs from a directory."""
        dir_path = Path(directory).resolve()
        pdf_paths = sorted(dir_path.glob("*.pdf"))
        if not pdf_paths:
            raise FileNotFoundError(f"No PDF files found in directory: {dir_path}")
        return self.ingest_files(pdf_paths)

    def get_index(self) -> VectorStoreIndex:
        """Get or load the VectorStoreIndex."""
        if self._index is None:
            col_name = self.index_manager.config.qdrant_collection_name
            if not self.index_manager.client.collection_exists(col_name):
                return self.ingest_directory(self.config.documents_path)
            points, _ = self.index_manager.client.scroll(col_name, limit=1, with_payload=True)
            if not points or points[0].payload.get("index_fingerprint") != self.fingerprint:
                raise ValueError("Index provenance mismatch; re-ingest into a versioned collection")
            self._index = self.index_manager.load_index()
        return self._index

    @property
    def fingerprint(self):
        return self.index_manager.fingerprint

    @staticmethod
    def serialize(nodes):
        return [
            {
                **n.node.metadata,
                "chunk_id": n.node.node_id,
                "text": n.node.get_content(),
                "score": n.score,
            }
            for n in nodes
        ]

    def candidates(self, query, top_k=20, mode="hybrid", embedding=None):
        if mode not in {"dense", "sparse", "hybrid"}:
            raise ValueError("Search mode must be dense, sparse, or hybrid")
        if top_k < 1:
            raise ValueError("top_k must be positive")
        retriever = self.get_index().as_retriever(
            similarity_top_k=top_k,
            sparse_top_k=top_k,
            hybrid_top_k=top_k,
            vector_store_query_mode={"dense": "default", "sparse": "sparse", "hybrid": "hybrid"}[
                mode
            ],
            alpha=0.5,
        )
        return retriever.retrieve(QueryBundle(query_str=query, embedding=embedding))

    def retrieve_with_trace(
        self, query, top_k=None, rerank_top_n=None, *, mode="hybrid", rerank=True
    ):
        start = time.perf_counter()
        initial = self.candidates(query, top_k or self.config.top_k, mode)
        retrieval_ms = (time.perf_counter() - start) * 1000
        trace = {
            "query": query,
            "mode": mode,
            "retrieval_ms": retrieval_ms,
            "initial_candidates": self.serialize(initial),
            "reranker": {"status": "disabled", "latency_ms": 0},
        }
        nodes = initial
        if rerank and getattr(self.config, "enable_reranker", False):
            ranker = self.reranker.model_copy(
                update={"top_n": rerank_top_n or self.config.rerank_top_n}
            )
            nodes, trace["reranker"] = ranker.rerank_with_trace(initial, query)
        else:
            cutoff = rerank_top_n or self.config.rerank_top_n
            nodes = initial[:cutoff]
            trace["reranker"] = {"status": "disabled", "latency_ms": 0}
        trace["final_ranking"] = self.serialize(nodes)
        trace["total_ms"] = (time.perf_counter() - start) * 1000
        return nodes, trace

    def retrieve(self, query, top_k=None, rerank_top_n=None, *, mode="hybrid", rerank=True):
        return self.retrieve_with_trace(query, top_k, rerank_top_n, mode=mode, rerank=rerank)[0]

    def search(self, query):
        nodes, trace = self.retrieve_with_trace(query)
        chunks = self.serialize(nodes)
        for chunk in chunks:
            chunk["retrieval_status"] = {
                "mode": trace["mode"],
                "reranker": trace["reranker"]["status"],
                "retrieval_ms": trace["retrieval_ms"],
                "rerank_ms": trace["reranker"]["latency_ms"],
            }
        return chunks

    def generate_answer(
        self,
        query: str,
        context_nodes: list[NodeWithScore] | None = None,
    ) -> str:
        """Generate an answer using the configured generation model."""
        nodes = context_nodes if context_nodes is not None else self.retrieve(query)
        context_text = "\n\n---\n\n".join([n.node.get_content() for n in nodes])
        prompt = (
            "You are an enterprise policy specialist. Answer the question accurately and "
            "concisely based on the provided policy context.\n\n"
            f"Context:\n{context_text}\n\n"
            f"Question: {query}\n\n"
            "Answer:"
        )
        headers = {
            "Authorization": f"Bearer {self.config.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://cloudscale.internal",
            "X-Title": "CloudScale RAG Generation",
        }
        payload = {
            "model": self.config.generation_model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(
                f"{self.config.openrouter_base_url.rstrip('/')}/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    def close(self) -> None:
        """Close vector store and underlying connections."""
        self.index_manager.close()
