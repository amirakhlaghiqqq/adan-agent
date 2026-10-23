"""CLI tool to audit and inspect chunk quality and required fields across Qdrant collections."""

from __future__ import annotations

import argparse
import sys

from adan.rag.config import load_config
from adan.rag.hybrid_store import create_qdrant_client
from adan.rag.pipeline import RAGPipeline
from adan.rag.quality_control import ChunkQCStatus, ChunkQualityController


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit Qdrant collection for chunk quality and required field completeness."
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Target Qdrant collection name to audit (default: from active config)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print details of every chunk audited",
    )

    args = parser.parse_args()
    config = load_config()
    client, _ = create_qdrant_client(config)
    qc = ChunkQualityController()

    target_collection = args.collection
    if not target_collection:
        pipeline = RAGPipeline(config)
        target_collection = pipeline.index_manager.config.qdrant_collection_name

    print("\n" + "=" * 78)
    print(f"  AUDITING COLLECTION: {target_collection}")
    print(f"  Qdrant URL:          {config.qdrant_url if not config.is_local_qdrant else 'local'}")
    print("=" * 78)

    if not client.collection_exists(target_collection):
        print(f"Error: Collection '{target_collection}' does not exist in Qdrant.")
        sys.exit(1)

    report = qc.audit_qdrant_collection(client, target_collection)
    qc.print_qc_report(report)

    if args.verbose:
        print("\n" + "=" * 78)
        print("                        DETAILED CHUNK LISTING")
        print("=" * 78)
        for i, d in enumerate(report.diagnostics):
            status_symbol = "✓" if d.status == ChunkQCStatus.PASSED else "✗"
            print(
                f"[{i:02d}] {status_symbol} Doc: {d.doc_id:<18} | "
                f"Chars: {d.char_count:<5} | Table: {str(d.is_table):<5} | "
                f"Callout: {str(d.has_policy_note):<5} | "
                f"Path: {d.header_path}"
            )
            if d.issues:
                for issue in d.issues:
                    print(f"     -> Issue: {issue}")
        print("=" * 78 + "\n")

    # Verify formula decoding across all chunks in target collection
    points, _ = client.scroll(target_collection, limit=200, with_payload=True)
    found_s3_2 = False
    for p in points:
        text = p.payload.get("text", "") or p.payload.get("_node_content", "")
        node_id = p.id
        if "formula-not-decoded" in text:
            raise AssertionError(f"Chunk {node_id} contains 'formula-not-decoded'!")
        clause_title = str(p.payload.get("clause_title", ""))
        header_path = str(p.payload.get("header_path", ""))
        if "3.2" in clause_title or "3.2" in header_path:
            if "sla_and_support_tier_policy" in str(p.payload.get("source_file", "")):
                found_s3_2 = True
                assert "Monthly Uptime Percentage" in text, (
                    f"Chunk {node_id} missing 'Monthly Uptime Percentage'"
                )
                assert "Downtime Minutes" in text, f"Chunk {node_id} missing 'Downtime Minutes'"
                assert "Total Scheduled Minutes in Month" in text, (
                    f"Chunk {node_id} missing 'Total Scheduled Minutes in Month'"
                )

    assert found_s3_2, "S3.2 calculation formula chunk was not found in collection!"
    print("✓ Formula Verification: Zero 'formula-not-decoded' and S3.2 terms fully validated.")

    if not report.is_clean:
        print(f"FAILED: Found {report.failed_count} failing chunks.")
        sys.exit(1)
    else:
        print("PASSED: All chunks passed Quality Control.")
        sys.exit(0)


if __name__ == "__main__":
    main()
