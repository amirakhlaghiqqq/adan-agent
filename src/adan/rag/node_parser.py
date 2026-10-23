"""Hierarchical Markdown node parser and metadata enricher."""

from __future__ import annotations

import logging
import re
from uuid import NAMESPACE_URL, uuid5

from llama_index.core import Document
from llama_index.core.node_parser import MarkdownNodeParser
from llama_index.core.schema import NodeRelationship, RelatedNodeInfo, TextNode

from adan.rag.quality_control import ChunkQualityController, QualityControlReport

logger = logging.getLogger(__name__)


def is_markdown_table(text: str) -> bool:
    """Check if the text contains a Markdown table (| header | ... |)."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    has_pipe_rows = sum(1 for line in lines if line.startswith("|") and line.endswith("|"))
    has_separator = any(re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", line) for line in lines)
    return has_pipe_rows >= 2 and has_separator


def has_policy_callout(text: str) -> bool:
    """Check if the text contains a policy callout note or disclaimer."""
    patterns = [
        r"(?:Policy Note|NOTE|IMPORTANT|DISCLAIMER|Compliance Statement):",
        r"\*\*Policy Note:\*\*",
        r"Corporate Governance & Compliance",
    ]
    return any(re.search(pat, text, re.IGNORECASE) for pat in patterns)


class PolicyMarkdownNodeParser:
    """Splits Markdown documents into hierarchical nodes and enriches them with layout metadata."""

    def __init__(
        self,
        include_metadata: bool = True,
        header_path_separator: str = " / ",
        qc_controller: ChunkQualityController | None = None,
    ):
        self.parser = MarkdownNodeParser(
            include_metadata=include_metadata,
            header_path_separator=header_path_separator,
        )
        self.qc_controller = qc_controller or ChunkQualityController()
        self.last_qc_report: QualityControlReport | None = None

    def get_nodes_from_documents(self, documents: list[Document]) -> list[TextNode]:
        """Parse documents into enriched TextNodes with quality control gating."""
        nodes = self.parser.get_nodes_from_documents(documents)
        enriched_nodes: list[TextNode] = []
        originals = {d.metadata.get("source_file"): d for d in documents}

        for node in nodes:
            text = node.get_content().strip()
            if not text:
                continue

            metadata = dict(node.metadata)
            doc_id = metadata.get("document_id", metadata.get("doc_id", "DOC-UNKNOWN"))
            spans = metadata.pop("_page_spans", [])
            if spans and metadata.get("source_file") in originals:
                original = originals[metadata["source_file"]].text
                start = original.find(text)
                if start >= 0:
                    pages = [
                        x["page"]
                        for x in spans
                        if x["start"] < start + len(text) and x["end"] > start
                    ]
                    if pages:
                        metadata.update(page_number=min(pages), page_numbers=pages)

            metadata["document_id"] = doc_id
            metadata["doc_id"] = doc_id
            metadata["policy_doc_id"] = doc_id

            header_path = metadata.get("header_path", "")

            # Extract clause heading if present on the first line
            first_line = text.splitlines()[0].strip() if text else ""
            if first_line.startswith("#"):
                clause_title = first_line.lstrip("#").strip()
                metadata["clause_title"] = clause_title
                clean_hp = header_path.strip().strip("/").strip()
                if clean_hp and clean_hp != clause_title:
                    header_path = f"{clean_hp} / {clause_title}"
                else:
                    header_path = clause_title
                metadata["header_path"] = header_path

            # Deterministic ID based on doc ID, header path, and text hash
            unique_id = str(uuid5(NAMESPACE_URL, f"{doc_id}:{header_path}:{text}"))

            # Detect structural features
            contains_table = is_markdown_table(text)
            contains_callout = has_policy_callout(text)

            metadata.update(
                {
                    "node_id": unique_id,
                    "chunk_id": unique_id,
                    "section": header_path or "Document overview",
                    "is_table": contains_table,
                    "has_policy_note": contains_callout,
                }
            )

            enriched = TextNode(
                id_=unique_id,
                text=text,
                metadata=metadata,
                excluded_llm_metadata_keys=["node_id", "file_path"],
                excluded_embed_metadata_keys=[
                    "node_id",
                    "chunk_id",
                    "file_path",
                    "source_file",
                    "source_sha256",
                    "index_fingerprint",
                ],
            )
            # CRITICAL: set source relationship so vector store serializers retain doc_id
            enriched.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=doc_id)
            enriched_nodes.append(enriched)

        # Apply Quality Control Gate (prune orphan headings, unescape HTML, validate fields)
        sanitized_nodes, qc_report = self.qc_controller.sanitize_and_filter_nodes(enriched_nodes)
        self.last_qc_report = qc_report

        logger.info(
            "Parsed %d documents into %d nodes (%d tables, %d callouts, QC Pass: %.1f%%)",
            len(documents),
            len(sanitized_nodes),
            sum(1 for n in sanitized_nodes if n.metadata.get("is_table")),
            sum(1 for n in sanitized_nodes if n.metadata.get("has_policy_note")),
            qc_report.pass_rate_pct,
        )
        return sanitized_nodes
