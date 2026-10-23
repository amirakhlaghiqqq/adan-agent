"""Integration tests for policy node parsing and Hybrid Qdrant index persistence."""

from __future__ import annotations

from llama_index.core.embeddings import MockEmbedding
from llama_index.core.schema import Document

from adan.rag.config import RAGConfig
from adan.rag.hybrid_store import HybridIndexManager
from adan.rag.node_parser import PolicyMarkdownNodeParser


def test_hybrid_index_preserves_metadata_and_reopens_from_disk(tmp_path):
    # 1. Verify structured node parsing with hierarchical sections, tables, and page metadata
    sample_doc = Document(
        text=(
            "## 1. Billing Terms\nPayment is due in 30 days.\n\n"
            "### 1.1 Service Credits\nCredits are 10% for P1 severity.\n"
        ),
        metadata={
            "doc_id": "DOC-SLA-2024-V2",
            "document_id": "DOC-SLA-2024-V2",
            "version": "2.0",
            "source_file": "sla_policy.pdf",
            "effective_date": "January 1, 2024",
            "classification": "Internal",
            "_page_spans": [
                {"page": 1, "start": 0, "end": 50},
                {"page": 2, "start": 51, "end": 150},
            ],
        },
    )
    parser = PolicyMarkdownNodeParser()
    nodes = parser.get_nodes_from_documents([sample_doc])
    assert len(nodes) >= 2
    assert all(n.metadata.get("doc_id") == "DOC-SLA-2024-V2" for n in nodes)
    assert all(n.metadata.get("clause_title") for n in nodes)
    assert all(n.metadata.get("chunk_id") == n.node_id for n in nodes)

    # 2. Verify HybridIndexManager builds into local embedded Qdrant, searches, and reopens
    cfg = RAGConfig(
        openrouter_api_key="sk-test",
        openrouter_embedding_model="mock",
        openrouter_reranker_model="mock",
        qdrant_url="",
        qdrant_local_path=tmp_path / "qdrant_data",
        qdrant_collection_name="test_embedded_collection",
    )
    manager = HybridIndexManager(cfg)
    manager.embed_model = MockEmbedding(embed_dim=8)

    index = manager.build_index(nodes)
    retriever = index.as_retriever(similarity_top_k=2)
    found = retriever.retrieve("Service Credits")
    assert len(found) >= 1
    assert any("Credit" in n.node.get_content() for n in found)

    fingerprint = manager.fingerprint
    manager.close()

    # 3. Reopen index from disk and verify persistence
    reopened_manager = HybridIndexManager(cfg)
    reopened_manager.embed_model = MockEmbedding(embed_dim=8)
    assert reopened_manager.fingerprint == fingerprint
    reopened_index = reopened_manager.load_index()
    reopened_retriever = reopened_index.as_retriever(similarity_top_k=2)
    reopened_found = reopened_retriever.retrieve("Billing Terms")
    assert len(reopened_found) >= 1
    reopened_manager.close()
