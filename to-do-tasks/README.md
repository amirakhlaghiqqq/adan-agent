# To-do tasks

| Task | Status | Benchmark |
|---|---|---|
| [Evaluate Jev and alternative coordinator models](evaluate-coordinator-models.md) | Specified; implementation and endpoint configuration pending | [64 labeled comparison cases](../evals/coordinator/benchmark.jsonl) |

The comparison benchmark has 16 document-only, 16 database-only, 16 hybrid,
and 16 no-source cases. It includes a fixed development/test split and grouped
paraphrases. The existing 48 RAG questions remain a separate regression set.

No provider requests or model comparisons have been executed. Credentials are
supplied later through environment variables, never stored in these documents.
