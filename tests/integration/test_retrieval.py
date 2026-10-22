from pathlib import Path

from llama_index.core.embeddings import MockEmbedding

from adan.rag.index import PolicyIndex, extract_nodes


def test_pdf_ingestion_preserves_pages_and_sections_and_index_reopens(tmp_path):
    nodes = extract_nodes(Path("data/documents"))
    assert {n.metadata["document_id"] for n in nodes} == {"DOC-BIL-2024-V3", "DOC-SLA-2024-V2"}
    assert all(n.metadata["page_number"] >= 1 and n.metadata["section"] for n in nodes)
    assert all(n.metadata["chunk_id"] == n.node_id for n in nodes)
    embed = MockEmbedding(embed_dim=8)
    index = PolicyIndex(Path("data/documents"), tmp_path / "index", embed_model=embed)
    found = index.search("service credit")
    assert len(found) == 5
    assert all(c["chunk_id"] and c["text"] and c["page_number"] for c in found)
    fingerprint = index.fingerprint
    index.close()
    reopened = PolicyIndex(Path("data/documents"), tmp_path / "index", embed_model=embed)
    assert reopened.fingerprint == fingerprint
    assert len(reopened.search("billing")) == 5
    reopened.close()
