from typing import Protocol


class Aggregator(Protocol):
    def build(self, question: str, input_context: list[str], chunks: list[dict]) -> dict: ...


class PassthroughAggregator:
    """Aggregates and deduplicates candidate chunks across multi-query retrieval."""

    def build(self, question: str, input_context: list[str], chunks: list[dict]) -> dict:
        seen = set()
        deduped = []
        for c in chunks:
            cid = c.get("chunk_id")
            if cid and cid not in seen:
                seen.add(cid)
                deduped.append(c)
            elif not cid:
                deduped.append(c)
        return {
            "version": "passthrough-v1-pending-design",
            "chunks": deduped,
            "source_chunk_ids": [c["chunk_id"] for c in deduped if "chunk_id" in c],
        }
