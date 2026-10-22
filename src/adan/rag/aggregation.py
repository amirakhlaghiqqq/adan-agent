from typing import Protocol


class Aggregator(Protocol):
    def build(self, question: str, input_context: list[str], chunks: list[dict]) -> dict: ...


class PassthroughAggregator:
    """Temporary transport adapter; the proposed aggregation algorithm remains pending."""

    def build(self, question: str, input_context: list[str], chunks: list[dict]) -> dict:
        return {
            "version": "passthrough-v1-pending-design",
            "chunks": chunks,
            "source_chunk_ids": [c["chunk_id"] for c in chunks],
        }
