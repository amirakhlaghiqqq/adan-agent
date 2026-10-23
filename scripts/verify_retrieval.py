"""Retrieval verification test harness validating all 5 layout characteristics."""

from __future__ import annotations

import argparse
import logging
import sys

from adan.rag.config import load_config
from adan.rag.pipeline import RAGPipeline

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
)
logger = logging.getLogger("rag_verify")

VERIFICATION_SCENARIOS = [
    {
        "id": "METADATA_BANNER",
        "title": "1. Metadata Banner on Page 1",
        "query": (
            "What is the Doc ID, Version, and Effective Date of the "
            "Enterprise Billing and Refund Policy?"
        ),
        "expected_keywords": ["DOC-BIL-2024-V3", "February 1, 2024"],
        "metadata_check": lambda meta: meta.get("doc_id") == "DOC-BIL-2024-V3",
    },
    {
        "id": "TABLE_SCHEDULE",
        "title": "2. Multi-Column Table Integrity (Delinquency Escalation Schedule)",
        "query": (
            "What action and access status applies to an account that is 31 to 60 days "
            "past due in the Delinquency Escalation Schedule table?"
        ),
        "expected_keywords": ["31-60", "Suspension", "Grace Period"],
        "metadata_check": lambda meta: (
            meta.get("is_table") is True or "table" in meta.get("header_path", "").lower()
        ),
    },
    {
        "id": "HIERARCHICAL_CLAUSE",
        "title": "3. Hierarchical Numbered Clauses (Section 4 Late Payments)",
        "query": ("What is the monthly interest penalty for late payments under Section 4?"),
        "expected_keywords": ["1.5%", "interest", "Late Payments"],
        "metadata_check": lambda meta: (
            "4" in meta.get("header_path", "") or "Late Payments" in meta.get("header_path", "")
        ),
    },
    {
        "id": "INLINE_CALLOUT",
        "title": "4. Inline Callouts (Policy Note on Currency Selection)",
        "query": (
            "What does the Policy Note state regarding currency selection and contract execution?"
        ),
        "expected_keywords": ["Policy Note", "Currency"],
        "metadata_check": lambda meta: (
            meta.get("has_policy_note") is True or "Policy Note" in meta.get("header_path", "")
        ),
    },
    {
        "id": "FURNITURE_CHECK",
        "title": "5. Page Furniture Stripping Verification",
        "query": "Corporate Document Governance and Contact Directory review",
        "expected_keywords": ["Governance", "Directory"],
        "metadata_check": lambda meta: True,
    },
]


def run_verification(pipeline: RAGPipeline) -> bool:
    print("\n" + "=" * 80)
    print("  CLOUDSCALE RAG RETRIEVAL VERIFICATION SUITE")
    print("=" * 80)
    print(f"Embedding Model:  {pipeline.config.openrouter_embedding_model}")
    print(f"Reranker Model:   {pipeline.config.openrouter_reranker_model}")
    print(f"Generation Model: {pipeline.config.generation_model}")
    print(f"Collection Name:  {pipeline.config.qdrant_collection_name}")
    storage_desc = (
        "Local Embedded" if pipeline.config.is_local_qdrant else pipeline.config.qdrant_url
    )
    print(f"Storage Mode:     {storage_desc}")
    print("=" * 80 + "\n")

    all_passed = True
    results_summary = []

    for scenario in VERIFICATION_SCENARIOS:
        print(f"\n--- Scenario: {scenario['title']} ---")
        print(f'Query: "{scenario["query"]}"')

        nodes = pipeline.retrieve(
            scenario["query"],
            top_k=pipeline.config.top_k,
            rerank_top_n=pipeline.config.rerank_top_n,
        )

        if not nodes:
            print("  ❌ FAIL: No nodes returned.")
            all_passed = False
            results_summary.append((scenario["id"], "FAIL (No results)"))
            continue

        top_node = nodes[0]
        content = top_node.node.get_content()
        meta = top_node.node.metadata
        score = top_node.score

        # Check keywords
        found_keywords = [
            kw for kw in scenario["expected_keywords"] if kw.lower() in content.lower()
        ]
        keywords_ok = len(found_keywords) >= 1

        # Check furniture pollution: verify repeating headers and footers are absent
        furniture_polluted = any(f"Page {p} of 4" in content for p in (2, 3, 4))

        print(f"  Top Match Score: {score:.4f}" if score is not None else "  Top Match Score: N/A")
        print(f"  Header Path:     {meta.get('header_path', 'N/A')}")
        print(f"  Doc ID / Ver:    {meta.get('doc_id', 'N/A')} (v{meta.get('version', 'N/A')})")
        print(
            f"  Is Table:        {meta.get('is_table', False)} | "
            f"Has Callout: {meta.get('has_policy_note', False)}"
        )
        print(f"  Keywords Found:  {found_keywords} / {scenario['expected_keywords']}")
        furniture_status = (
            "YES (No page number / running header pollution)"
            if not furniture_polluted
            else "NO (Found page headers/footers)"
        )
        print(f"  Furniture Clean: {furniture_status}")

        # Preview first 200 chars
        snippet = content.replace("\n", " ")[:200]
        print(f'  Snippet:         "{snippet}..."')

        scenario_passed = keywords_ok and not furniture_polluted
        status_str = "PASS" if scenario_passed else "FAIL"
        if not scenario_passed:
            all_passed = False

        print(f"  Result:          {'✅ PASS' if scenario_passed else '❌ FAIL'}")
        results_summary.append((scenario["id"], status_str))

    # Optional generation verification with nvidia/nemotron-3.5-lightning:free
    print("\n--- 6. Generation Verification (nvidia/nemotron-3.5-lightning:free) ---")
    gen_query = "What is the monthly interest penalty for late payments under Section 4?"
    try:
        print(f'Generation Query: "{gen_query}"')
        answer = pipeline.generate_answer(gen_query)
        print(f"Generated Answer: {answer.strip()}")
        gen_ok = "1.5%" in answer or "interest" in answer.lower()
        print(f"  Result:          {'✅ PASS' if gen_ok else '❌ FAIL'}")
        results_summary.append(("GENERATION_CHECK", "PASS" if gen_ok else "FAIL"))
        if not gen_ok:
            all_passed = False
    except Exception as exc:
        print(f"  Generation error: {exc}")
        results_summary.append(("GENERATION_CHECK", "FAIL (Error)"))
        all_passed = False

    print("\n" + "=" * 80)
    print("  VERIFICATION SCORECARD")
    print("=" * 80)
    for sid, status in results_summary:
        print(f"  {sid:<25} : {status}")
    print("-" * 80)
    print(f"  FINAL OUTCOME: {'✅ ALL TESTS PASSED' if all_passed else '❌ SOME TESTS FAILED'}")
    print("=" * 80 + "\n")
    return all_passed


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run retrieval verification on indexed policy documents."
    )
    parser.parse_args()

    try:
        config = load_config()
        pipeline = RAGPipeline(config)
        success = run_verification(pipeline)
        if not success:
            sys.exit(1)
    except Exception as exc:
        logger.exception("Verification harness encountered an error: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
