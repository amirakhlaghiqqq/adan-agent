"""Unit tests for the Chunk Quality Control (QC) and Field Validation System."""

from __future__ import annotations

import textwrap

import pytest
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

from adan.rag.quality_control import (
    ChunkQCStatus,
    ChunkQualityController,
    is_markdown_table_valid,
    is_orphan_heading,
)


@pytest.fixture
def qc_controller() -> ChunkQualityController:
    return ChunkQualityController()


def test_orphan_heading_detection():
    assert is_orphan_heading("## 2. Invoicing, Payment Methods & Net Terms") is True
    assert is_orphan_heading("### 5.3 Tax Exemption") is True
    assert is_orphan_heading("# CloudScale Policies\n## Section 1") is True
    assert is_orphan_heading("") is True
    assert (
        is_orphan_heading(
            "## 2. Invoicing\nCloudScale accepts corporate wire transfers and ACH payments."
        )
        is False
    )


def test_markdown_table_validation():
    valid_table = textwrap.dedent("""
    | Plan | Notice Required | Proration |
    | :--- | :--- | :--- |
    | Starter | 30 calendar days | End-of-month |
    | Growth | 60 calendar days | Prorated daily |
    """).strip()
    is_valid, msg = is_markdown_table_valid(valid_table)
    assert is_valid is True

    # Missing separator
    invalid_table_no_sep = textwrap.dedent("""
    | Plan | Notice Required |
    | Starter | 30 calendar days |
    """).strip()
    is_valid, msg = is_markdown_table_valid(invalid_table_no_sep)
    assert is_valid is False
    assert "missing" in msg.lower()

    # Mismatched column count
    invalid_table_cols = textwrap.dedent("""
    | Plan | Notice Required | Extra |
    | :--- | :--- |
    | Starter | 30 calendar days |
    """).strip()
    is_valid, msg = is_markdown_table_valid(invalid_table_cols)
    assert is_valid is False
    assert "header has" in msg.lower()


def test_validate_node_complete_passes(qc_controller: ChunkQualityController):
    node = TextNode(
        id_="test-node-1",
        text="This is a substantive policy clause explaining enterprise credit rules.",
        metadata={
            "doc_id": "DOC-BIL-2024-V3",
            "policy_doc_id": "DOC-BIL-2024-V3",
            "version": "3.0",
            "effective_date": "February 1, 2024",
            "classification": "Enterprise Customer Policy",
            "source_file": "enterprise_billing_and_refund_policy.pdf",
            "header_path": "4. Late Payments / 4.1 Grace Period",
            "clause_title": "4.1 Grace Period",
            "is_table": False,
            "has_policy_note": False,
        },
    )
    node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id="DOC-BIL-2024-V3")

    diag = qc_controller.validate_node(node)
    assert diag.status == ChunkQCStatus.PASSED
    assert len(diag.missing_fields) == 0
    assert len(diag.issues) == 0
    assert diag.doc_id == "DOC-BIL-2024-V3"


def test_validate_node_missing_fields_fails(qc_controller: ChunkQualityController):
    # Node missing doc_id, version, and effective_date
    node = TextNode(
        id_="test-node-defective",
        text="Some policy text without proper document metadata.",
        metadata={
            "source_file": "test.pdf",
            "header_path": "1. Overview",
            "clause_title": "1. Overview",
            "is_table": False,
            "has_policy_note": False,
        },
    )

    diag = qc_controller.validate_node(node)
    assert diag.status == ChunkQCStatus.FAILED
    assert "doc_id" in diag.missing_fields
    assert "version" in diag.missing_fields
    assert "effective_date" in diag.missing_fields
    assert "classification" in diag.missing_fields


def test_validate_orphan_heading_fails(qc_controller: ChunkQualityController):
    node = TextNode(
        id_="test-node-orphan",
        text="## 2. Invoicing, Payment Methods & Net Terms",
        metadata={
            "doc_id": "DOC-BIL-2024-V3",
            "policy_doc_id": "DOC-BIL-2024-V3",
            "version": "3.0",
            "effective_date": "February 1, 2024",
            "classification": "Enterprise Customer Policy",
            "source_file": "billing.pdf",
            "header_path": "2. Invoicing",
            "clause_title": "2. Invoicing",
            "is_table": False,
            "has_policy_note": False,
        },
    )

    diag = qc_controller.validate_node(node)
    assert diag.status == ChunkQCStatus.FAILED
    assert any("Orphan heading" in iss for iss in diag.issues)


def test_sanitize_and_filter_nodes_prunes_orphans_and_unescapes(
    qc_controller: ChunkQualityController,
):
    orphan_node = TextNode(
        id_="orphan",
        text="## 2. Invoicing &amp; Net Terms",
        metadata={"doc_id": "DOC-BIL-2024-V3", "source_file": "billing.pdf"},
    )
    valid_node = TextNode(
        id_="valid",
        text="### 2.1 Net-30 Terms\nPayments &amp; wire transfers are accepted with net-30 days.",
        metadata={
            "doc_id": "DOC-BIL-2024-V3",
            "source_file": "billing.pdf",
            "version": "3.0",
            "effective_date": "February 1, 2024",
            "classification": "Enterprise Customer Policy",
            "header_path": "2. Invoicing &amp; Net Terms / 2.1 Net-30 Terms",
            "clause_title": "2.1 Net-30 Terms",
        },
    )

    clean_nodes, report = qc_controller.sanitize_and_filter_nodes([orphan_node, valid_node])

    # Orphan node should be pruned
    assert len(clean_nodes) == 1
    assert clean_nodes[0].id_ == "valid"
    # HTML entities must be unescaped
    assert "&amp;" not in clean_nodes[0].get_content()
    assert "&amp;" not in clean_nodes[0].metadata["header_path"]
    # ref_doc_id must be assigned
    assert clean_nodes[0].ref_doc_id == "DOC-BIL-2024-V3"
    assert clean_nodes[0].metadata["policy_doc_id"] == "DOC-BIL-2024-V3"
    assert clean_nodes[0].metadata["qc_status"] == "PASSED"
    assert report.total_chunks == 1
    assert report.is_clean is True
