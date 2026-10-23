"""Unit tests for RAG configuration, Docling layout parser, Markdown node parser,
and OpenRouter reranker.
"""

from __future__ import annotations

import textwrap
import unittest.mock as mock

import pytest
from llama_index.core.schema import Document, NodeWithScore, QueryBundle, TextNode

from adan.rag.config import RAGConfig
from adan.rag.docling_parser import extract_metadata_banner, strip_residual_furniture
from adan.rag.node_parser import PolicyMarkdownNodeParser, has_policy_callout, is_markdown_table
from adan.rag.reranker import OpenRouterRerank


def test_rag_config_validation():
    # Valid config
    cfg = RAGConfig(
        openrouter_api_key="sk-test",
        openrouter_embedding_model="nvidia/nemotron-3-embed-1b:free",
        openrouter_reranker_model="nvidia/llama-nemotron-rerank-vl-1b-v2:free",
        generation_model="nvidia/nemotron-3.5-lightning:free",
        qdrant_url="",
        qdrant_collection_name="enterprise_policies",
    )
    cfg.validate()
    assert cfg.is_local_qdrant is True

    # Remote/server Qdrant URL
    remote_cfg = RAGConfig(
        openrouter_api_key="sk-test",
        openrouter_embedding_model="nvidia/nemotron-3-embed-1b:free",
        openrouter_reranker_model="nvidia/llama-nemotron-rerank-vl-1b-v2:free",
        qdrant_url="http://localhost:6333",
        qdrant_collection_name="enterprise_policies",
    )
    assert remote_cfg.is_local_qdrant is False

    # Missing API key
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY is required"):
        RAGConfig(
            openrouter_api_key="",
            openrouter_embedding_model="test-embed",
            openrouter_reranker_model="test-rerank",
        ).validate()

    # Missing embedding model
    with pytest.raises(ValueError, match="OPENROUTER_EMBEDDING_MODEL must not be empty"):
        RAGConfig(
            openrouter_api_key="sk-test",
            openrouter_embedding_model="",
            openrouter_reranker_model="test-rerank",
        ).validate()

    # Missing reranker model
    with pytest.raises(ValueError, match="OPENROUTER_RERANKER_MODEL must not be empty"):
        RAGConfig(
            openrouter_api_key="sk-test",
            openrouter_embedding_model="test-embed",
            openrouter_reranker_model="",
        ).validate()


def test_metadata_banner_extraction():
    sample_text = """
    # CloudScale Inc.
    ## Enterprise Billing, Payment & Refund Policy
    **Doc ID:** DOC-BIL-2024-V3
    **Version:** 3.2.0
    **Effective Date:** February 1, 2024
    **Classification:** Commercial In Confidence
    **Review Cycle:** Annual / Q1 Mandatory
    **Target Audience:** Finance, Sales, Account Management
    """
    banner = extract_metadata_banner(sample_text)
    assert banner.get("doc_id") == "DOC-BIL-2024-V3"
    assert banner.get("version") == "3.2.0"
    assert "February 1, 2024" in banner.get("effective_date", "")
    assert "Commercial In Confidence" in banner.get("classification", "")
    assert "Annual" in banner.get("review_cycle", "")


def test_strip_residual_furniture():
    raw_markdown = textwrap.dedent("""
    ## 1. Overview
    This is an important sentence that crosses page boundaries\x0c
    Page 1 of 4
    and continues smoothly on the next page.
    Doc ID: DOC-BIL-2024-V3



    ## 2. Next Section
    """).strip()
    cleaned = strip_residual_furniture(raw_markdown)
    assert "Page 1 of 4" not in cleaned
    assert "\x0c" not in cleaned
    expected_str = (
        "This is an important sentence that crosses page boundaries\n"
        "and continues smoothly on the next page."
    )
    assert expected_str in cleaned


def test_structural_feature_detection():
    table_text = """
    | Plan | Notice Required | Proration |
    | :--- | :--- | :--- |
    | Starter | 30 calendar days | End-of-month |
    | Growth | 60 calendar days | Prorated daily |
    """
    assert is_markdown_table(table_text) is True
    assert is_markdown_table("Just some regular text without a table.") is False

    callout_text = (
        "**Policy Note:** Invoices under formal dispute are shielded from automated lockouts."
    )
    assert has_policy_callout(callout_text) is True
    assert has_policy_callout("Regular policy terms without special notes.") is False


def test_markdown_node_parser_enrichment():
    markdown = textwrap.dedent("""
    # Enterprise Billing Policy

    ## 1. Purpose and Scope
    This policy defines all commercial billing cycles.

    ## 2. Payment Terms
    ### 2.1 Permitted Payment Instruments
    | Method | Latency | Surcharge |
    | :--- | :--- | :--- |
    | Wire Transfer | Same-day | $0 |

    **Policy Note:** Wire transfers require verified routing numbers.
    """).strip()
    doc = Document(
        text=markdown,
        metadata={"doc_id": "DOC-BIL-2024-V3", "version": "3.2.0", "source_file": "billing.pdf"},
    )
    parser = PolicyMarkdownNodeParser()
    nodes = parser.get_nodes_from_documents([doc])

    assert len(nodes) >= 2
    # Check that metadata banner was propagated
    for node in nodes:
        assert node.metadata.get("doc_id") == "DOC-BIL-2024-V3"
        assert "header_path" in node.metadata

    # Check table and callout detection
    table_nodes = [n for n in nodes if n.metadata.get("is_table")]
    assert len(table_nodes) >= 1
    callout_nodes = [n for n in nodes if n.metadata.get("has_policy_note")]
    assert len(callout_nodes) >= 1


def test_openrouter_rerank_postprocessor_mocked():
    node1 = TextNode(text="Paris is the capital of France.", id_="node-1")
    node2 = TextNode(text="Berlin is the capital of Germany.", id_="node-2")
    nodes = [NodeWithScore(node=node1, score=0.5), NodeWithScore(node=node2, score=0.4)]

    reranker = OpenRouterRerank(
        api_key="sk-mock-key",
        model="nvidia/llama-nemotron-rerank-vl-1b-v2:free",
        top_n=2,
    )

    mock_response = mock.MagicMock()
    mock_response.json.return_value = {
        "results": [
            {"index": 1, "relevance_score": 0.98},
            {"index": 0, "relevance_score": 0.32},
        ]
    }
    mock_response.raise_for_status = mock.MagicMock()

    with mock.patch("httpx.Client.post", return_value=mock_response):
        query_bundle = QueryBundle(query_str="Germany capital")
        reranked = reranker.postprocess_nodes(nodes, query_bundle=query_bundle)
        assert len(reranked) == 2
        assert reranked[0].node.id_ == "node-2"
        assert reranked[0].score == 0.98
        assert reranked[1].node.id_ == "node-1"
        assert reranked[1].score == 0.32


def test_openrouter_rerank_fallback_on_error():
    node1 = TextNode(text="First chunk", id_="n1")
    node2 = TextNode(text="Second chunk", id_="n2")
    nodes = [NodeWithScore(node=node1, score=0.9), NodeWithScore(node=node2, score=0.8)]

    reranker = OpenRouterRerank(api_key="sk-mock", top_n=2)

    with mock.patch("httpx.Client.post", side_effect=Exception("Network error")):
        fallback = reranker.postprocess_nodes(nodes, query_bundle=QueryBundle(query_str="test"))
        assert len(fallback) == 2
        # Retains original order
        assert fallback[0].node.id_ == "n1"
        assert fallback[1].node.id_ == "n2"


def test_rag_pipeline_generate_answer_mocked():
    from adan.rag.pipeline import RAGPipeline

    cfg = RAGConfig(
        openrouter_api_key="sk-test",
        openrouter_embedding_model="nvidia/nemotron-3-embed-1b:free",
        openrouter_reranker_model="nvidia/llama-nemotron-rerank-vl-1b-v2:free",
        generation_model="nvidia/nemotron-3.5-lightning:free",
        qdrant_url="",
    )
    pipeline = RAGPipeline(cfg)
    mock_node = NodeWithScore(node=TextNode(text="Late fee is 1.5%"), score=0.9)
    mock_resp = mock.MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": "The late payment penalty is 1.5%."}}]
    }
    mock_resp.raise_for_status = mock.MagicMock()
    with mock.patch("httpx.Client.post", return_value=mock_resp):
        ans = pipeline.generate_answer("penalty", context_nodes=[mock_node])
        assert "1.5%" in ans


def test_search_plan_schema_up_to_three_queries():
    from adan.schemas import SearchPlan

    # Valid: 1, 2, 3 queries
    assert len(SearchPlan(queries=["q1"]).queries) == 1
    assert len(SearchPlan(queries=["q1", "q2"]).queries) == 2
    assert len(SearchPlan(queries=["q1", "q2", "q3"]).queries) == 3

    # Invalid: 0 or >3 queries
    with pytest.raises(Exception):
        SearchPlan(queries=[])
    with pytest.raises(Exception):
        SearchPlan(queries=["q1", "q2", "q3", "q4"])


def test_passthrough_aggregator_deduplication():
    from adan.rag.aggregation import PassthroughAggregator

    aggregator = PassthroughAggregator()
    chunks = [
        {"chunk_id": "c1", "text": "Chunk 1"},
        {"chunk_id": "c2", "text": "Chunk 2"},
        {"chunk_id": "c1", "text": "Chunk 1 duplicate"},
        {"chunk_id": "c3", "text": "Chunk 3"},
        {"chunk_id": "c2", "text": "Chunk 2 duplicate"},
    ]
    artifact = aggregator.build("test question", [], chunks)
    assert artifact["source_chunk_ids"] == ["c1", "c2", "c3"]
    assert len(artifact["chunks"]) == 3
    assert [c["chunk_id"] for c in artifact["chunks"]] == ["c1", "c2", "c3"]


def test_search_plan_schema_up_to_three_queries():
    from adan.schemas import SearchPlan

    # Valid: 1, 2, 3 queries
    assert len(SearchPlan(queries=["q1"]).queries) == 1
    assert len(SearchPlan(queries=["q1", "q2"]).queries) == 2
    assert len(SearchPlan(queries=["q1", "q2", "q3"]).queries) == 3

    # Invalid: 0 or >3 queries
    with pytest.raises(Exception):
        SearchPlan(queries=[])
    with pytest.raises(Exception):
        SearchPlan(queries=["q1", "q2", "q3", "q4"])


def test_passthrough_aggregator_deduplication():
    from adan.rag.aggregation import PassthroughAggregator

    aggregator = PassthroughAggregator()
    chunks = [
        {"chunk_id": "c1", "text": "Chunk 1"},
        {"chunk_id": "c2", "text": "Chunk 2"},
        {"chunk_id": "c1", "text": "Chunk 1 duplicate"},
        {"chunk_id": "c3", "text": "Chunk 3"},
        {"chunk_id": "c2", "text": "Chunk 2 duplicate"},
    ]
    artifact = aggregator.build("test question", [], chunks)
    assert artifact["source_chunk_ids"] == ["c1", "c2", "c3"]
    assert len(artifact["chunks"]) == 3
    assert [c["chunk_id"] for c in artifact["chunks"]] == ["c1", "c2", "c3"]
