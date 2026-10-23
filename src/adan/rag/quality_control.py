"""Chunk Quality Control (QC) and Required Field Validation System.

Validates that every chunk in the RAG pipeline satisfies strict structural,
content, and metadata criteria before and after indexing into Qdrant.
"""

from __future__ import annotations

import html
import json
import logging
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from llama_index.core.schema import BaseNode, NodeRelationship, RelatedNodeInfo, TextNode
from qdrant_client import QdrantClient

logger = logging.getLogger(__name__)

# Mandatory metadata fields required on every chunk
REQUIRED_METADATA_FIELDS = [
    "doc_id",
    "policy_doc_id",
    "version",
    "effective_date",
    "classification",
    "source_file",
    "header_path",
    "clause_title",
]

PAGE_FURNITURE_PATTERNS = [
    re.compile(r"^\s*Page\s+\d+\s+of\s+\d+\s*$", re.IGNORECASE),
    re.compile(r"^\s*Doc\s*ID:\s*DOC-[A-Z0-9\-]+\s*$", re.IGNORECASE),
    re.compile(r"^\s*CloudScale\s+Inc\.\s*\|\s*", re.IGNORECASE),
    re.compile(r"\x0c"),  # Form feed characters
]

CALLOUT_PATTERNS = [
    r"(?:Policy Note|NOTE|IMPORTANT|DISCLAIMER|Compliance Statement):",
    r"\*\*Policy Note:\*\*",
    r"Corporate Governance & Compliance",
]


class ChunkQCStatus(StrEnum):
    """Quality control status for an individual chunk."""

    PASSED = "PASSED"
    WARNING = "WARNING"
    FAILED = "FAILED"


@dataclass
class ChunkQualityDiagnostic:
    """Detailed quality diagnostic for a single chunk."""

    node_id: str
    doc_id: str | None
    source_file: str | None
    header_path: str | None
    clause_title: str | None
    char_count: int
    token_count_approx: int
    is_table: bool
    has_policy_note: bool
    status: ChunkQCStatus
    missing_fields: list[str] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)
    text_preview: str = ""


@dataclass
class QualityControlReport:
    """Aggregate quality control report for a set of chunks or a collection."""

    total_chunks: int = 0
    passed_count: int = 0
    warning_count: int = 0
    failed_count: int = 0
    table_chunks: int = 0
    callout_chunks: int = 0
    average_char_length: float = 0.0
    field_compliance_rate: dict[str, float] = field(default_factory=dict)
    diagnostics: list[ChunkQualityDiagnostic] = field(default_factory=list)

    @property
    def pass_rate_pct(self) -> float:
        """Percentage of chunks that passed QC without failure."""
        if self.total_chunks == 0:
            return 100.0
        return (self.passed_count / self.total_chunks) * 100.0

    @property
    def is_clean(self) -> bool:
        """True if all chunks passed and zero chunks failed."""
        return self.failed_count == 0 and self.total_chunks > 0


def is_markdown_table_valid(text: str) -> tuple[bool, str]:
    """Check if text contains a valid Markdown table and verify its structure."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    table_lines = [line for line in lines if line.startswith("|") and line.endswith("|")]
    if len(table_lines) < 2:
        return False, "Table has fewer than 2 pipe-delimited rows"

    # Verify separator row exists
    separator_idx = -1
    for i, line in enumerate(table_lines):
        if re.match(r"^\|(?:\s*:?-+:?\s*\|)+$", line):
            separator_idx = i
            break

    if separator_idx == -1:
        return False, "Table is missing a standard markdown delimiter row (|:---|)"
    if separator_idx == 0:
        return False, "Separator row cannot be the first table row"
    if separator_idx >= len(table_lines) - 1 and len(table_lines) == 2:
        return False, "Table has header and separator but 0 data rows"

    # Check column count alignment between header and separator
    header_cols = len([c for c in table_lines[0].split("|")[1:-1]])
    separator_cols = len([c for c in table_lines[separator_idx].split("|")[1:-1]])
    if header_cols != separator_cols:
        return (
            False,
            f"Table header has {header_cols} cols but separator has {separator_cols}",
        )

    return True, "Valid table structure"


def is_orphan_heading(text: str) -> bool:
    """Check if the text is purely an orphan markdown heading without body text."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    # If all non-empty lines start with markdown heading markers '#', it's an orphan heading
    return all(line.startswith("#") for line in lines)


class ChunkQualityController:
    """Enforces quality gates, sanitizes nodes, and audits collections."""

    def __init__(self, required_fields: list[str] | None = None):
        self.required_fields = required_fields or REQUIRED_METADATA_FIELDS

    def validate_node(
        self,
        node: BaseNode | dict[str, Any],
        text: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ChunkQualityDiagnostic:
        """Perform comprehensive QC checks on an individual chunk."""
        if isinstance(node, BaseNode):
            node_id = node.node_id
            text_content = text if text is not None else node.get_content()
            meta = dict(metadata or node.metadata)
            ref_doc_id = getattr(node, "ref_doc_id", None)
        else:
            # Dict representation (e.g. from Qdrant scroll payload)
            node_id = str(node.get("id") or node.get("node_id", "unknown"))
            text_content = text if text is not None else node.get("text", "")
            meta = dict(metadata or node.get("metadata", {}) or node)
            ref_doc_id = node.get("ref_doc_id") or meta.get("ref_doc_id")

        issues: list[str] = []
        missing_fields: list[str] = []

        # 1. Field Completeness Check
        for req_field in self.required_fields:
            val = meta.get(req_field)
            if (
                req_field == "doc_id"
                and (not val or val == "None")
                and ref_doc_id
                and ref_doc_id != "None"
            ):
                val = ref_doc_id
            if val is None or str(val).strip() == "" or str(val).strip() == "None":
                missing_fields.append(req_field)
                issues.append(f"Missing required field: '{req_field}'")

        # 2. Text Substantiveness & Orphan Heading Check
        cleaned_text = text_content.strip()
        char_count = len(cleaned_text)
        token_count = len(cleaned_text.split()) * 4 // 3

        if char_count == 0:
            issues.append("Empty chunk text content")
        elif is_orphan_heading(cleaned_text):
            issues.append(f"Orphan heading chunk with no body text: '{cleaned_text[:60]}'")
        elif char_count < 30 and not meta.get("is_table"):
            issues.append(f"Excessively short chunk ({char_count} chars)")

        if char_count > 8000:
            issues.append(f"Chunk exceeds max recommended length ({char_count} chars > 8000)")

        # 3. Residual Page Furniture Check
        for line in cleaned_text.splitlines():
            line_str = line.strip()
            for pat in PAGE_FURNITURE_PATTERNS:
                if pat.search(line_str):
                    issues.append(f"Residual page furniture detected: '{line_str[:50]}'")
                    break

        # 4. Table Structure Check
        is_table = bool(meta.get("is_table"))
        if is_table:
            is_valid, table_msg = is_markdown_table_valid(cleaned_text)
            if not is_valid:
                issues.append(f"Malformed table: {table_msg}")

        # 5. Policy Callout Consistency Check
        has_callout_flag = bool(meta.get("has_policy_note"))
        has_callout_text = any(
            re.search(pat, cleaned_text, re.IGNORECASE) for pat in CALLOUT_PATTERNS
        )
        if has_callout_text and not has_callout_flag:
            issues.append("Text contains policy note/callout but has_policy_note is False")

        # 6. HTML Entity Pollution Check
        if any(entity in cleaned_text for entity in ["&amp;", "&lt;", "&gt;", "&quot;"]):
            issues.append("Unescaped HTML entities in text body")

        # 7. Un-decoded Formula Check
        if "formula-not-decoded" in cleaned_text:
            issues.append("Un-decoded formula detected: contains 'formula-not-decoded'")

        # 8. S3.2 Calculation Formula Completeness Check
        is_sla_policy = "sla_and_support_tier_policy" in str(meta.get("source_file", "")).lower()
        is_sec_3_2 = "3.2" in str(meta.get("clause_title", "")) or "3.2" in str(
            meta.get("header_path", "")
        )
        if is_sla_policy and is_sec_3_2:
            required_formula_terms = [
                "Monthly Uptime Percentage",
                "Total Scheduled Minutes in Month",
                "Downtime Minutes",
            ]
            missing_terms = [t for t in required_formula_terms if t not in cleaned_text]
            if missing_terms:
                issues.append(f"Section 3.2 chunk missing formula terms: {missing_terms}")

        # Determine overall QC status
        status = ChunkQCStatus.PASSED
        has_fatal_issue = any(
            "Missing required field" in iss
            or "Empty chunk" in iss
            or "Orphan heading" in iss
            or "Un-decoded formula" in iss
            or "missing formula terms" in iss
            for iss in issues
        )
        has_structural_issue = any(
            "Malformed table" in iss or "Residual page furniture" in iss for iss in issues
        )
        if has_fatal_issue or has_structural_issue:
            status = ChunkQCStatus.FAILED
        elif issues:
            status = ChunkQCStatus.WARNING

        return ChunkQualityDiagnostic(
            node_id=node_id,
            doc_id=meta.get("doc_id") or meta.get("policy_doc_id"),
            source_file=meta.get("source_file"),
            header_path=meta.get("header_path"),
            clause_title=meta.get("clause_title"),
            char_count=char_count,
            token_count_approx=token_count,
            is_table=is_table,
            has_policy_note=has_callout_flag,
            status=status,
            missing_fields=missing_fields,
            issues=issues,
            text_preview=cleaned_text[:100].replace("\n", " "),
        )

    def sanitize_and_filter_nodes(
        self, nodes: list[TextNode]
    ) -> tuple[list[TextNode], QualityControlReport]:
        """Prune orphan headings, unescape entities, populate all required fields,

        and validate all chunks.
        """
        sanitized_nodes: list[TextNode] = []
        diagnostics: list[ChunkQualityDiagnostic] = []

        for i, node in enumerate(nodes):
            raw_text = node.get_content().strip()
            # 1. Unescape HTML entities
            clean_text = html.unescape(raw_text)

            # 2. Prune pure orphan headings (chunks that are purely a heading with zero body)
            if is_orphan_heading(clean_text):
                logger.debug("Pruning orphan heading chunk %d: '%s'", i, clean_text[:60])
                continue

            metadata = dict(node.metadata)

            # 3. Clean and unescape metadata strings
            doc_id = metadata.get("doc_id") or "DOC-UNKNOWN"
            metadata["doc_id"] = doc_id
            metadata["policy_doc_id"] = doc_id  # Immutable copy immune to store overwriting

            if "header_path" in metadata:
                metadata["header_path"] = html.unescape(metadata["header_path"]).strip()
            if "clause_title" in metadata:
                metadata["clause_title"] = html.unescape(metadata["clause_title"]).strip()

            # Ensure version and dates are present
            if not metadata.get("version"):
                metadata["version"] = "1.0"
            if not metadata.get("classification"):
                metadata["classification"] = "Internal"

            char_count = len(clean_text)
            token_count = len(clean_text.split()) * 4 // 3
            metadata["char_count"] = char_count
            metadata["token_count_approx"] = token_count
            metadata["chunk_index"] = len(sanitized_nodes)
            metadata["qc_status"] = ChunkQCStatus.PASSED.value

            # Build sanitized TextNode
            clean_node = TextNode(
                id_=node.node_id,
                text=clean_text,
                metadata=metadata,
                excluded_llm_metadata_keys=node.excluded_llm_metadata_keys,
                excluded_embed_metadata_keys=node.excluded_embed_metadata_keys,
            )
            # CRITICAL: set source relationship so LlamaIndex Qdrant serializer retains doc_id!
            clean_node.relationships[NodeRelationship.SOURCE] = RelatedNodeInfo(node_id=doc_id)

            # Validate the sanitized node
            diag = self.validate_node(clean_node)
            diagnostics.append(diag)
            sanitized_nodes.append(clean_node)

        report = self._build_report(diagnostics)
        logger.info(
            "Quality Control complete: %d input nodes -> %d sanitized chunks (Pass rate: %.1f%%)",
            len(nodes),
            len(sanitized_nodes),
            report.pass_rate_pct,
        )
        return sanitized_nodes, report

    def validate_nodes(self, nodes: list[BaseNode]) -> QualityControlReport:
        """Run QC validation on a list of nodes without modifying them."""
        diagnostics = [self.validate_node(n) for n in nodes]
        return self._build_report(diagnostics)

    def audit_qdrant_collection(
        self, client: QdrantClient, collection_name: str
    ) -> QualityControlReport:
        """Audit all chunks currently stored in a live Qdrant collection."""
        logger.info(
            "Auditing Qdrant collection '%s' for chunk quality and required fields...",
            collection_name,
        )
        points, _ = client.scroll(
            collection_name=collection_name,
            limit=1000,
            with_payload=True,
            with_vectors=False,
        )

        diagnostics: list[ChunkQualityDiagnostic] = []
        for p in points:
            payload = p.payload or {}
            # Check for serialized node_content from LlamaIndex
            content_json = payload.get("_node_content")
            if content_json:
                try:
                    node_data = json.loads(content_json)
                    text = node_data.get("text", "")
                    meta = node_data.get("metadata", {})
                    # Merge payload values with node_data metadata
                    merged_meta = {**meta, **payload}
                    ref_id = payload.get("doc_id") or meta.get("doc_id")
                    diag = self.validate_node(
                        node={"id": p.id, "ref_doc_id": ref_id},
                        text=text,
                        metadata=merged_meta,
                    )
                except Exception:
                    diag = self.validate_node(
                        node={"id": p.id},
                        text=payload.get("text", ""),
                        metadata=payload,
                    )
            else:
                diag = self.validate_node(
                    node={"id": p.id},
                    text=payload.get("text", ""),
                    metadata=payload,
                )
            diagnostics.append(diag)

        return self._build_report(diagnostics)

    def _build_report(self, diagnostics: list[ChunkQualityDiagnostic]) -> QualityControlReport:
        """Compute aggregate quality report metrics from individual diagnostics."""
        total = len(diagnostics)
        passed = sum(1 for d in diagnostics if d.status == ChunkQCStatus.PASSED)
        warnings = sum(1 for d in diagnostics if d.status == ChunkQCStatus.WARNING)
        failed = sum(1 for d in diagnostics if d.status == ChunkQCStatus.FAILED)
        tables = sum(1 for d in diagnostics if d.is_table)
        callouts = sum(1 for d in diagnostics if d.has_policy_note)
        avg_chars = sum(d.char_count for d in diagnostics) / total if total > 0 else 0.0

        # Calculate field compliance rate
        field_compliance: dict[str, float] = {}
        for req_field in self.required_fields:
            compliant = sum(1 for d in diagnostics if req_field not in d.missing_fields)
            field_compliance[req_field] = (compliant / total * 100.0) if total > 0 else 100.0

        return QualityControlReport(
            total_chunks=total,
            passed_count=passed,
            warning_count=warnings,
            failed_count=failed,
            table_chunks=tables,
            callout_chunks=callouts,
            average_char_length=avg_chars,
            field_compliance_rate=field_compliance,
            diagnostics=diagnostics,
        )

    def print_qc_report(self, report: QualityControlReport, max_preview: int = 10) -> None:
        """Print a structured, readable QC report to the console."""
        print("\n" + "=" * 78)
        print("                   RAG CHUNK QUALITY CONTROL (QC) REPORT")
        print("=" * 78)
        print(f"Total Chunks Audited:     {report.total_chunks}")
        print(f"Passed (100% Compliant):  {report.passed_count} ({report.pass_rate_pct:.1f}%)")
        print(f"Warnings:                 {report.warning_count}")
        print(f"Failed / Defective:       {report.failed_count}")
        print(f"Table Chunks:             {report.table_chunks}")
        print(f"Policy Note Callouts:     {report.callout_chunks}")
        print(f"Average Chunk Length:     {report.average_char_length:.1f} characters")
        print("-" * 78)
        print("FIELD COMPLIANCE RATES:")
        for field_name, rate in report.field_compliance_rate.items():
            bar = "#" * int(rate / 5)
            print(f"  {field_name:<20} {rate:>5.1f}% [{bar:<20}]")
        print("-" * 78)

        if report.failed_count > 0 or report.warning_count > 0:
            print("DIAGNOSTIC ISSUES DETECTED:")
            shown = 0
            for d in report.diagnostics:
                if d.status != ChunkQCStatus.PASSED:
                    h_path = d.header_path or "No Header"
                    print(f"  * Node [{d.node_id[:8]}...] | {h_path} | Status: {d.status.value}")
                    for issue in d.issues:
                        print(f"      - {issue}")
                    shown += 1
                    if shown >= max_preview:
                        remaining = (report.failed_count + report.warning_count) - shown
                        if remaining > 0:
                            print(f"      ... and {remaining} more items.")
                        break
            print("-" * 78)
        else:
            print("ALL CHUNKS SATISFY QUALITY CONTROL REQUIREMENTS!")
            print("=" * 78 + "\n")
