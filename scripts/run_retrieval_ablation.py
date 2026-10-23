"""End-to-End Evaluation and Ablation Study for RAG Retrieval System.

Evaluates:
1. Dense-only retrieval (nvidia/nemotron-3-embed-1b:free)
2. Sparse-only retrieval (FastEmbed BM25: Qdrant/bm25)
3. Hybrid retrieval (Dense + Sparse)
4. Effect of Cross-Encoder Reranker (nvidia/llama-nemotron-rerank-vl-1b-v2:free)
5. Query Decomposition (Monolithic single-query vs Decomposed sub-query)

Outputs:
- experiments/retrieval-ablation/traces/{qid}.json
- experiments/retrieval-ablation/summary.json
- experiments/retrieval-ablation/corpus.jsonl
- experiments/retrieval-ablation/index_manifest.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import random
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

WORKSPACE_ROOT = Path(__file__).resolve().parents[1]
if str(WORKSPACE_ROOT) not in sys.path:
    sys.path.insert(0, str(WORKSPACE_ROOT))

from llama_index.core import QueryBundle
from llama_index.core.schema import NodeWithScore
from qdrant_client import QdrantClient

from adan.rag.config import RAGConfig, load_config
from adan.rag.pipeline import RAGPipeline
from evals.rag.retrieval_judgments import build_annotations
from evals.rag.retrieval_metrics import (
    CUTOFFS,
    budget_allocations,
    mean,
    merge_rankings,
    paired_interval,
    score,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("retrieval_ablation")

CACHE_DIR = Path(".cache/adan/ablation")
CACHE_DIR.mkdir(parents=True, exist_ok=True)
EMB_CACHE_FILE = CACHE_DIR / "query_embeddings.json"
RERANK_CACHE_FILE = CACHE_DIR / "rerank_cache.json"

_RERANK_CACHE: dict[str, Any] = {}
if RERANK_CACHE_FILE.exists():
    try:
        with open(RERANK_CACHE_FILE, "r", encoding="utf-8") as f:
            _RERANK_CACHE = json.load(f)
    except Exception:
        _RERANK_CACHE = {}


def save_rerank_cache():
    try:
        with open(RERANK_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(_RERANK_CACHE, f)
    except Exception as e:
        logger.warning("Could not save rerank cache: %s", e)


def safe_round(val: float | None, n: int = 4) -> float | None:
    return round(val, n) if val is not None else None


def load_benchmark(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def get_qdrant_corpus(client: QdrantClient, collection_name: str) -> list[dict[str, Any]]:
    points, _ = client.scroll(collection_name, limit=200, with_payload=True)
    points = sorted(points, key=lambda p: str(p.id))
    corpus = []
    for p in points:
        nc = json.loads(p.payload.get("_node_content", "{}"))
        chunk_id = p.payload.get("chunk_id") or nc.get("id_") or str(p.id)
        text = nc.get("text", "")
        corpus.append({
            "chunk_id": chunk_id,
            "text": text,
            "metadata": p.payload,
        })
    return corpus


def precompute_query_embeddings(
    pipeline: RAGPipeline, queries: list[str], batch_size: int = 16
) -> dict[str, list[float]]:
    cache: dict[str, list[float]] = {}
    if EMB_CACHE_FILE.exists():
        try:
            with open(EMB_CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
            logger.info("Loaded %d query embeddings from cache: %s", len(cache), EMB_CACHE_FILE)
        except Exception as e:
            logger.warning("Failed to load embeddings cache: %s", e)

    missing = [q for q in queries if q not in cache]
    if missing:
        logger.info("Precomputing %d missing query embeddings in batches of %d...", len(missing), batch_size)
        embed_model = pipeline.index_manager.embed_model
        for i in range(0, len(missing), batch_size):
            batch = missing[i : i + batch_size]
            t0 = time.perf_counter()
            try:
                embeddings = embed_model.get_text_embedding_batch(batch)
                for q, emb in zip(batch, embeddings):
                    cache[q] = emb
                dt = (time.perf_counter() - t0) * 1000
                logger.info("Embedded batch %d-%d in %.1f ms", i, i + len(batch), dt)
            except Exception as e:
                logger.error("Batch embedding failed: %s; falling back to individual calls", e)
                for q in batch:
                    try:
                        cache[q] = embed_model.get_query_embedding(q)
                    except Exception as exc:
                        logger.error("Individual embedding failed for '%s': %s", q[:40], exc)
                        raise

        with open(EMB_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f)
        logger.info("Saved %d embeddings to cache", len(cache))

    return cache


def retrieve_query_candidates(
    pipeline: RAGPipeline,
    query: str,
    top_k: int,
    mode: str,
    embedding: list[float] | None,
) -> tuple[list[dict[str, Any]], float]:
    """Retrieve top_k candidates for a single query."""
    t0 = time.perf_counter()
    index = pipeline.get_index()
    vector_store_mode = {"dense": "default", "sparse": "sparse", "hybrid": "hybrid"}[mode]
    retriever = index.as_retriever(
        similarity_top_k=top_k,
        sparse_top_k=top_k,
        hybrid_top_k=top_k,
        vector_store_query_mode=vector_store_mode,
        alpha=0.5,
    )
    bundle = QueryBundle(query_str=query, embedding=embedding)
    nodes = retriever.retrieve(bundle)
    latency_ms = (time.perf_counter() - t0) * 1000

    serialized = []
    for r in nodes:
        meta = r.node.metadata
        cid = r.node.node_id or meta.get("chunk_id")
        serialized.append({
            "chunk_id": cid,
            "score": float(r.score) if r.score is not None else 0.0,
            "text": r.node.get_content(),
            "metadata": meta,
            "_node": r,
        })
    return serialized, latency_ms


def execute_rerank(
    pipeline: RAGPipeline,
    nodes_with_score: list[NodeWithScore],
    query: str,
    top_n: int = 20,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rerank candidates using OpenRouter cross-encoder reranker, with persistent caching."""
    if not nodes_with_score:
        return [], {"status": "empty", "latency_ms": 0.0}

    chunk_ids = [n.node.node_id or n.node.metadata.get("chunk_id", "") for n in nodes_with_score]
    cache_key = f"{query.strip()}::" + ",".join(chunk_ids[:top_n])

    if cache_key in _RERANK_CACHE:
        cached = _RERANK_CACHE[cache_key]
        # Re-attach _node from current nodes_with_score
        node_map = {n.node.node_id or n.node.metadata.get("chunk_id"): n for n in nodes_with_score}
        serialized = []
        for item in cached["serialized"]:
            cid = item["chunk_id"]
            serialized.append({
                **item,
                "_node": node_map.get(cid, None),
            })
        return serialized, cached["trace"]

    ranker = pipeline.reranker.model_copy(update={"top_n": min(top_n, len(nodes_with_score))})
    reranked_nodes, trace = ranker.rerank_with_trace(nodes_with_score, query)
    serialized = []
    clean_for_cache = []
    for r in reranked_nodes:
        meta = r.node.metadata
        cid = r.node.node_id or meta.get("chunk_id")
        item_dict = {
            "chunk_id": cid,
            "score": float(r.score) if r.score is not None else 0.0,
            "text": r.node.get_content(),
            "metadata": meta,
        }
        clean_for_cache.append(dict(item_dict))
        serialized.append({
            **item_dict,
            "_node": r,
        })

    # Cache if successful
    if trace.get("status") == "success":
        _RERANK_CACHE[cache_key] = {
            "serialized": clean_for_cache,
            "trace": trace,
        }
        save_rerank_cache()

    return serialized, trace


def run_single_question_ablation(
    qid: str,
    case: dict[str, Any],
    plan: dict[str, Any],
    judgment: dict[str, Any],
    pipeline: RAGPipeline,
    embeddings_map: dict[str, list[float]],
    run_reranker: bool = True,
) -> dict[str, Any]:
    question = case["question"]
    sub_queries = plan["queries"]
    m = len(sub_queries)
    budgets = budget_allocations(m, budget=20)
    relevant_set = set(judgment["relevant_chunk_ids"])

    trace: dict[str, Any] = {
        "question_id": qid,
        "question": question,
        "difficulty": case["difficulty"],
        "category": case["category"],
        "num_requirements": len(case["required_document_evidence"]),
        "required_evidence_groups": [g["requirement_id"] for g in case["required_document_evidence"]],
        "relevant_chunk_ids": judgment["relevant_chunk_ids"],
        "single_query": question,
        "decomposed_queries": [
            {
                "query": sq["query"],
                "requirement_ids": sq["requirement_ids"],
                "budget": b,
            }
            for sq, b in zip(sub_queries, budgets)
        ],
        "configurations": {},
    }

    # 1. Monolithic candidates (top_k=20)
    mono_cands: dict[str, tuple[list[dict[str, Any]], float]] = {}
    q_emb = embeddings_map.get(question)
    for mode in ("dense", "sparse", "hybrid"):
        cands, lat = retrieve_query_candidates(
            pipeline,
            query=question,
            top_k=20,
            mode=mode,
            embedding=q_emb if mode in ("dense", "hybrid") else None,
        )
        mono_cands[mode] = (cands, lat)

    # 2. Decomposed candidates (top_k=b per sub-query, then merged)
    decomp_cands: dict[str, tuple[list[dict[str, Any]], float]] = {}
    for mode in ("dense", "sparse", "hybrid"):
        total_lat = 0.0
        rankings = []
        for sq, b in zip(sub_queries, budgets):
            sq_text = sq["query"]
            sq_emb = embeddings_map.get(sq_text)
            cands, lat = retrieve_query_candidates(
                pipeline,
                query=sq_text,
                top_k=b,
                mode=mode,
                embedding=sq_emb if mode in ("dense", "hybrid") else None,
            )
            total_lat += lat
            rankings.append(cands)
        merged = merge_rankings(rankings)
        decomp_cands[mode] = (merged, total_lat)

    # Store base configs: dense_only, sparse_only, hybrid_no_rerank (both mono and decomp)
    configs_to_process = [
        ("dense_only_monolithic", mono_cands["dense"][0], mono_cands["dense"][1], "dense", "monolithic", False),
        ("dense_only_decomposed", decomp_cands["dense"][0], decomp_cands["dense"][1], "dense", "decomposed", False),
        ("sparse_only_monolithic", mono_cands["sparse"][0], mono_cands["sparse"][1], "sparse", "monolithic", False),
        ("sparse_only_decomposed", decomp_cands["sparse"][0], decomp_cands["sparse"][1], "sparse", "decomposed", False),
        ("hybrid_no_rerank_monolithic", mono_cands["hybrid"][0], mono_cands["hybrid"][1], "hybrid", "monolithic", False),
        ("hybrid_no_rerank_decomposed", decomp_cands["hybrid"][0], decomp_cands["hybrid"][1], "hybrid", "decomposed", False),
    ]

    # Reranking configurations: hybrid_rerank (and dense_rerank)
    if run_reranker:
        # Hybrid Monolithic Rerank
        hybrid_mono_nodes = [c["_node"] for c in mono_cands["hybrid"][0]]
        reranked_mono, rr_trace_mono = execute_rerank(pipeline, hybrid_mono_nodes, question, top_n=20)
        mono_rr_lat = rr_trace_mono.get("latency_ms", 0.0)
        configs_to_process.append((
            "hybrid_rerank_monolithic",
            reranked_mono,
            mono_cands["hybrid"][1] + mono_rr_lat,
            "hybrid",
            "monolithic",
            True,
        ))

        # Hybrid Decomposed Rerank (rerank merged pool against original question)
        hybrid_decomp_nodes = [c["_node"] for c in decomp_cands["hybrid"][0]]
        reranked_decomp, rr_trace_decomp = execute_rerank(pipeline, hybrid_decomp_nodes, question, top_n=20)
        decomp_rr_lat = rr_trace_decomp.get("latency_ms", 0.0)
        configs_to_process.append((
            "hybrid_rerank_decomposed",
            reranked_decomp,
            decomp_cands["hybrid"][1] + decomp_rr_lat,
            "hybrid",
            "decomposed",
            True,
        ))

        # Dense Monolithic Rerank (optional cross-ablation)
        dense_mono_nodes = [c["_node"] for c in mono_cands["dense"][0]]
        reranked_dense_mono, rr_dense_trace = execute_rerank(pipeline, dense_mono_nodes, question, top_n=20)
        dense_rr_lat = rr_dense_trace.get("latency_ms", 0.0)
        configs_to_process.append((
            "dense_rerank_monolithic",
            reranked_dense_mono,
            mono_cands["dense"][1] + dense_rr_lat,
            "dense",
            "monolithic",
            True,
        ))

    for name, cands, total_lat, mode, strategy, is_rerank in configs_to_process:
        # Score at all cutoffs k in [1, 3, 5, 10, 20]
        metrics_by_k = {}
        for k in CUTOFFS:
            metrics_by_k[str(k)] = score(cands, judgment, k)

        clean_cands = []
        for rank_idx, c in enumerate(cands, 1):
            clean_cands.append({
                "rank": rank_idx,
                "chunk_id": c["chunk_id"],
                "score": c["score"],
                "is_relevant": c["chunk_id"] in relevant_set,
                "section": c["metadata"].get("section") or c["metadata"].get("clause_title", ""),
                "source_file": c["metadata"].get("source_file", ""),
            })

        trace["configurations"][name] = {
            "mode": mode,
            "strategy": strategy,
            "rerank": is_rerank,
            "total_latency_ms": round(total_lat, 2),
            "num_candidates": len(cands),
            "candidates": clean_cands,
            "metrics_by_k": metrics_by_k,
        }

    return trace


def run_full_ablation(
    benchmark_path: Path = Path("evals/rag/benchmark.jsonl"),
    output_dir: Path = Path("experiments/retrieval-ablation"),
    skip_reranker: bool = False,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    traces_dir = output_dir / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)

    config = load_config()
    pipeline = RAGPipeline(config)
    client = pipeline.index_manager.client
    collection_name = pipeline.index_manager.config.qdrant_collection_name

    logger.info("Connected to Qdrant collection: %s", collection_name)
    cases = load_benchmark(benchmark_path)
    logger.info("Loaded %d benchmark cases", len(cases))

    corpus = get_qdrant_corpus(client, collection_name)
    logger.info("Fetched %d chunks from active Qdrant collection", len(corpus))

    # Build source-reviewed judgments and plans
    judgments, plans = build_annotations(cases, corpus)
    logger.info("Annotations verified for %d cases", len(judgments))

    # Collect all unique queries
    unique_queries = set(c["question"] for c in cases)
    for qid, p in plans.items():
        for sq in p["queries"]:
            unique_queries.add(sq["query"])
    query_list = sorted(unique_queries)
    logger.info("Total distinct queries across monolithic and decomposed: %d", len(query_list))

    # Precompute / fetch embeddings
    embeddings_map = precompute_query_embeddings(pipeline, query_list)

    # Run ablation question by question
    all_traces: dict[str, dict[str, Any]] = {}
    config_names = [
        "dense_only_monolithic",
        "dense_only_decomposed",
        "sparse_only_monolithic",
        "sparse_only_decomposed",
        "hybrid_no_rerank_monolithic",
        "hybrid_no_rerank_decomposed",
    ]
    if not skip_reranker:
        config_names.extend([
            "hybrid_rerank_monolithic",
            "hybrid_rerank_decomposed",
            "dense_rerank_monolithic",
        ])

    logger.info("Starting ablation runs across %d questions for configs: %s", len(cases), config_names)
    start_time = time.perf_counter()

    for idx, case in enumerate(cases, 1):
        qid = case["question_id"]
        t_case0 = time.perf_counter()
        trace = run_single_question_ablation(
            qid=qid,
            case=case,
            plan=plans[qid],
            judgment=judgments[qid],
            pipeline=pipeline,
            embeddings_map=embeddings_map,
            run_reranker=not skip_reranker,
        )
        all_traces[qid] = trace

        # Save individual per-query trace
        trace_file = traces_dir / f"{qid}.json"
        with open(trace_file, "w", encoding="utf-8") as f:
            json.dump(trace, f, indent=2)

        dt_case = (time.perf_counter() - t_case0) * 1000
        logger.info(
            "[%02d/%02d] Processed %s (%s, reqs=%d) in %.1f ms",
            idx,
            len(cases),
            qid,
            case["difficulty"],
            len(case["required_document_evidence"]),
            dt_case,
        )

        # Rate-limit safety margin for free-tier reranker
        if not skip_reranker:
            time.sleep(0.3)

    total_duration = time.perf_counter() - start_time
    logger.info("Completed all %d benchmark cases in %.2f seconds", len(cases), total_duration)

    # Compute aggregate metrics per configuration
    summary: dict[str, Any] = {
        "metadata": {
            "run_timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "benchmark_cases": len(cases),
            "collection_name": collection_name,
            "fingerprint": pipeline.fingerprint,
            "embedding_model": config.openrouter_embedding_model,
            "sparse_model": "Qdrant/bm25",
            "reranker_model": config.openrouter_reranker_model if not skip_reranker else "none",
            "cutoffs": list(CUTOFFS),
            "total_duration_seconds": round(total_duration, 2),
        },
        "configurations": {},
        "slices": {},
        "paired_comparisons": {},
    }

    # Slices definitions
    slices = {
        "all": cases,
        "difficulty_easy": [c for c in cases if c["difficulty"] == "easy"],
        "difficulty_medium": [c for c in cases if c["difficulty"] == "medium"],
        "difficulty_hard": [c for c in cases if c["difficulty"] == "hard"],
        "category_document": [c for c in cases if c["category"] == "document"],
        "category_hybrid": [c for c in cases if c["category"] == "hybrid"],
        "single_requirement": [c for c in cases if len(c["required_document_evidence"]) == 1],
        "multi_requirement": [c for c in cases if len(c["required_document_evidence"]) > 1],
    }

    for cfg in config_names:
        cfg_summary: dict[str, Any] = {"by_k": {}, "latency_ms": {}}

        latencies = [all_traces[c["question_id"]]["configurations"][cfg]["total_latency_ms"] for c in cases]
        latencies_sorted = sorted(latencies)
        cfg_summary["latency_ms"] = {
            "mean": safe_round(mean(latencies), 2),
            "p50": safe_round(latencies_sorted[int(0.50 * len(latencies_sorted))], 2),
            "p95": safe_round(latencies_sorted[int(0.95 * len(latencies_sorted))], 2),
            "min": safe_round(min(latencies), 2),
            "max": safe_round(max(latencies), 2),
        }

        for k in CUTOFFS:
            recalls = [all_traces[c["question_id"]]["configurations"][cfg]["metrics_by_k"][str(k)]["evidence_recall"] for c in cases]
            successes = [all_traces[c["question_id"]]["configurations"][cfg]["metrics_by_k"][str(k)]["all_evidence_success"] for c in cases]
            precisions = [all_traces[c["question_id"]]["configurations"][cfg]["metrics_by_k"][str(k)]["context_precision"] for c in cases]
            ndcgs = [all_traces[c["question_id"]]["configurations"][cfg]["metrics_by_k"][str(k)]["ndcg"] for c in cases]

            cfg_summary["by_k"][str(k)] = {
                "evidence_recall": safe_round(mean(recalls), 4),
                "all_evidence_success": safe_round(mean(successes), 4),
                "context_precision": safe_round(mean(precisions), 4),
                "ndcg": safe_round(mean(ndcgs), 4),
            }

        summary["configurations"][cfg] = cfg_summary

    # Slice evaluation at key cutoff k=5
    for slice_name, slice_cases in slices.items():
        summary["slices"][slice_name] = {"count": len(slice_cases), "configs": {}}
        for cfg in config_names:
            recalls_k5 = [
                all_traces[c["question_id"]]["configurations"][cfg]["metrics_by_k"]["5"]["evidence_recall"]
                for c in slice_cases
            ]
            succ_k5 = [
                all_traces[c["question_id"]]["configurations"][cfg]["metrics_by_k"]["5"]["all_evidence_success"]
                for c in slice_cases
            ]
            prec_k5 = [
                all_traces[c["question_id"]]["configurations"][cfg]["metrics_by_k"]["5"]["context_precision"]
                for c in slice_cases
            ]
            ndcg_k5 = [
                all_traces[c["question_id"]]["configurations"][cfg]["metrics_by_k"]["5"]["ndcg"]
                for c in slice_cases
            ]
            summary["slices"][slice_name]["configs"][cfg] = {
                "recall@5": safe_round(mean(recalls_k5), 4),
                "success@5": safe_round(mean(succ_k5), 4),
                "precision@5": safe_round(mean(prec_k5), 4),
                "ndcg@5": safe_round(mean(ndcg_k5), 4),
            }

    # Paired bootstrap comparisons
    # Compare key pairs at k=5 and k=20
    comparisons_to_run = [
        ("hybrid_no_rerank_monolithic", "dense_only_monolithic", "Hybrid vs Dense (Monolithic)"),
        ("hybrid_no_rerank_monolithic", "sparse_only_monolithic", "Hybrid vs Sparse (Monolithic)"),
        ("hybrid_rerank_monolithic", "hybrid_no_rerank_monolithic", "Reranker vs No-Rerank (Hybrid Monolithic)"),
        ("hybrid_no_rerank_decomposed", "hybrid_no_rerank_monolithic", "Decomposed vs Monolithic (Hybrid)"),
        ("dense_only_decomposed", "dense_only_monolithic", "Decomposed vs Monolithic (Dense)"),
        ("sparse_only_decomposed", "sparse_only_monolithic", "Decomposed vs Monolithic (Sparse)"),
        ("hybrid_rerank_decomposed", "hybrid_rerank_monolithic", "Decomposed vs Monolithic (Hybrid + Rerank)"),
    ]

    for cfg_a, cfg_b, label in comparisons_to_run:
        if cfg_a not in config_names or cfg_b not in config_names:
            continue
        comp_result: dict[str, Any] = {"label": label, "config_a": cfg_a, "config_b": cfg_b, "cutoffs": {}}
        for k in (3, 5, 10, 20):
            # Evidence Recall delta
            deltas_recall = [
                all_traces[c["question_id"]]["configurations"][cfg_a]["metrics_by_k"][str(k)]["evidence_recall"]
                - all_traces[c["question_id"]]["configurations"][cfg_b]["metrics_by_k"][str(k)]["evidence_recall"]
                for c in cases
            ]
            deltas_succ = [
                all_traces[c["question_id"]]["configurations"][cfg_a]["metrics_by_k"][str(k)]["all_evidence_success"]
                - all_traces[c["question_id"]]["configurations"][cfg_b]["metrics_by_k"][str(k)]["all_evidence_success"]
                for c in cases
            ]
            deltas_prec = [
                all_traces[c["question_id"]]["configurations"][cfg_a]["metrics_by_k"][str(k)]["context_precision"]
                - all_traces[c["question_id"]]["configurations"][cfg_b]["metrics_by_k"][str(k)]["context_precision"]
                for c in cases
                if all_traces[c["question_id"]]["configurations"][cfg_a]["metrics_by_k"][str(k)]["context_precision"] is not None
                and all_traces[c["question_id"]]["configurations"][cfg_b]["metrics_by_k"][str(k)]["context_precision"] is not None
            ]
            deltas_ndcg = [
                all_traces[c["question_id"]]["configurations"][cfg_a]["metrics_by_k"][str(k)]["ndcg"]
                - all_traces[c["question_id"]]["configurations"][cfg_b]["metrics_by_k"][str(k)]["ndcg"]
                for c in cases
                if all_traces[c["question_id"]]["configurations"][cfg_a]["metrics_by_k"][str(k)]["ndcg"] is not None
                and all_traces[c["question_id"]]["configurations"][cfg_b]["metrics_by_k"][str(k)]["ndcg"] is not None
            ]

            comp_result["cutoffs"][str(k)] = {
                "recall_delta": paired_interval(deltas_recall),
                "success_delta": paired_interval(deltas_succ),
                "precision_delta": paired_interval(deltas_prec),
                "ndcg_delta": paired_interval(deltas_ndcg),
            }
        summary["paired_comparisons"][f"{cfg_a}__vs__{cfg_b}"] = comp_result

    # Save summary.json
    summary_file = output_dir / "summary.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info("Saved summary to %s", summary_file)

    # Print summary tables to console
    print("\n" + "=" * 100)
    print("                      RAG RETRIEVAL ABLATION BENCHMARK RESULTS")
    print("=" * 100)
    print(f"{'Configuration':<32} | {'Recall@5':<8} | {'Success@5':<9} | {'Prec@5':<8} | {'NDCG@5':<8} | {'Recall@20':<9} | {'Latency p50':<11}")
    print("-" * 100)
    for cfg in config_names:
        c_k5 = summary["configurations"][cfg]["by_k"]["5"]
        c_k20 = summary["configurations"][cfg]["by_k"]["20"]
        lat = summary["configurations"][cfg]["latency_ms"]
        print(
            f"{cfg:<32} | {c_k5['evidence_recall']:<8.4f} | {c_k5['all_evidence_success']:<9.4f} | "
            f"{c_k5['context_precision']:<8.4f} | {c_k5['ndcg']:<8.4f} | {c_k20['evidence_recall']:<9.4f} | "
            f"{lat['p50']:<8.1f} ms"
        )
    print("=" * 100 + "\n")

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run RAG retrieval ablation and evaluation.")
    parser.add_argument("--skip-reranker", action="store_true", help="Skip remote reranker calls")
    parser.add_argument("--output-dir", type=Path, default=Path("experiments/retrieval-ablation"))
    args = parser.parse_args()

    run_full_ablation(output_dir=args.output_dir, skip_reranker=args.skip_reranker)


if __name__ == "__main__":
    main()
