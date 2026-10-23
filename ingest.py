"""CLI ingestion entrypoint for the Docling + LlamaIndex + Qdrant Hybrid RAG Pipeline."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Enforce CPU-only processing for ingestion
os.environ["CUDA_VISIBLE_DEVICES"] = ""

from adan.rag.pipeline import RAGPipeline
from config import load_config

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [INGESTION] [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("rag_ingest")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest enterprise policy PDFs into local Qdrant with hybrid indexing."
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=None,
        help="Path to a single PDF document to ingest",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path("data/documents"),
        help="Path to directory containing PDF policies (default: data/documents)",
    )
    parser.add_argument(
        "--collection",
        type=str,
        default=None,
        help="Override Qdrant collection name (default: from config/env)",
    )

    args = parser.parse_args()

    try:
        config = load_config()
        if args.collection:
            # Overwrite collection name in frozen dataclass via object.__setattr__ or recreation
            from dataclasses import replace

            config = replace(config, qdrant_collection_name=args.collection)

        print("\n" + "=" * 70)
        print(" [INGESTION] CLOUDSCALE RAG PIPELINE (Docling + Qdrant Hybrid)")
        print("=" * 70)
        print(f"[INGESTION] Embedding Model:  {config.openrouter_embedding_model}")
        print(f"[INGESTION] Reranker Model:   {config.openrouter_reranker_model}")
        print(f"[INGESTION] Generation Model: {config.generation_model}")
        print("[INGESTION] Device Mode:      CPU Only (CUDA Disabled)")
        storage_desc = (
            f"Local Embedded: {config.qdrant_local_path}"
            if config.is_local_qdrant
            else config.qdrant_url
        )
        print(f"[INGESTION] Qdrant Storage:   {storage_desc}")
        print(f"[INGESTION] Collection Name:  {config.qdrant_collection_name}")
        print("-" * 70)

        pipeline = RAGPipeline(config)

        if args.file:
            print(f"[INGESTION] Parsing & indexing single file: {args.file}...")
            pipeline.ingest_files([args.file])
        else:
            print(f"[INGESTION] Parsing & indexing directory: {args.dir}...")
            pipeline.ingest_directory(args.dir)

        # Execute Post-Ingestion Quality Control Audit on Collection
        print("\n[INGESTION] Running Quality Control Audit on indexed chunks...")
        report = pipeline.audit_collection()
        pipeline.qc_controller.print_qc_report(report)

        if not report.is_clean:
            print(f"[INGESTION] FAILED: Quality control detected {report.failed_count} failing chunks.")
            sys.exit(1)
        else:
            pct_msg = f"{report.total_chunks}/{report.total_chunks}"
            print(f"[INGESTION] SUCCESS: 100% of chunks ({pct_msg}) passed Quality Control.")

        print("\n" + "=" * 70)
        print(" [INGESTION] COMPLETE - COLLECTION READY FOR HYBRID SEARCH")
        print("=" * 70 + "\n")

    except Exception as exc:
        logger.exception("Ingestion failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
