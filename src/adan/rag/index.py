import hashlib
import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode
from llama_index.vector_stores.qdrant import QdrantVectorStore
from qdrant_client import QdrantClient

SOURCES = {
    "enterprise_billing_and_refund_policy.pdf": "DOC-BIL-2024-V3",
    "sla_and_support_tier_policy.pdf": "DOC-SLA-2024-V2",
}
CHUNKING_VERSION = "page-section-v1"


def extract_nodes(directory: Path) -> list[TextNode]:
    nodes = []
    for filename, document_id in SOURCES.items():
        path = directory / filename
        text = subprocess.run(
            ["pdftotext", "-layout", str(path), "-"],
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        ).stdout
        pages = text.split("\f")
        if not pages[-1].strip():
            pages.pop()
        repeated = Counter(
            line.strip() for page in pages for line in set(page.splitlines()) if line.strip()
        )
        section = "Document overview"
        for page_number, page in enumerate(pages, 1):
            lines = [
                line.rstrip()
                for line in page.splitlines()
                if not re.fullmatch(r"\s*\d+\s*", line)
                and repeated[line.strip()] < max(3, len(pages))
            ]
            blocks, current = [], []
            for line in lines:
                if re.match(r"^\s*\d+(?:\.\d+)*\.?\s+[A-Z]", line):
                    if current:
                        blocks.append((section, "\n".join(current)))
                    section, current = line.strip(), [line]
                else:
                    current.append(line)
            if current:
                blocks.append((section, "\n".join(current)))
            for title, block in blocks:
                # Preserve table rows together; split oversized sections at paragraph boundaries.
                paragraphs = re.split(r"\n\s*\n", block.strip())
                pieces, piece = [], ""
                for paragraph in paragraphs:
                    if piece and len(piece) + len(paragraph) > 2000:
                        pieces.append(piece)
                        piece = ""
                    piece += ("\n\n" if piece else "") + paragraph
                if piece:
                    pieces.append(piece)
                for content in pieces:
                    identifier = str(uuid5(NAMESPACE_URL, f"{document_id}:{page_number}:{content}"))
                    nodes.append(
                        TextNode(
                            id_=identifier,
                            text=content,
                            metadata={
                                "chunk_id": identifier,
                                "document_id": document_id,
                                "source_file": filename,
                                "page_number": page_number,
                                "section": title,
                            },
                            excluded_embed_metadata_keys=["chunk_id", "source_file"],
                            excluded_llm_metadata_keys=["chunk_id"],
                        )
                    )
    return nodes


class PolicyIndex:
    def __init__(
        self, documents_path: Path, index_path: Path, *, embed_model, top_k: int = 5, url: str = ""
    ):
        nodes = extract_nodes(documents_path)
        embedding_config = {
            "class": type(embed_model).__name__,
            "model": embed_model.model_name,
            "dimension": getattr(embed_model, "embed_dim", None),
            "doc_embed_type": getattr(embed_model, "doc_embed_type", None),
        }
        digest = hashlib.sha256(CHUNKING_VERSION.encode() + json.dumps(embedding_config).encode())
        for filename in SOURCES:
            digest.update((documents_path / filename).read_bytes())
        self.fingerprint = digest.hexdigest()
        self.collection = "cloudscale_policies_" + self.fingerprint[:16]
        index_path.mkdir(parents=True, exist_ok=True)
        self.client = QdrantClient(url=url) if url else QdrantClient(path=str(index_path))
        store = QdrantVectorStore(client=self.client, collection_name=self.collection)
        if not self.client.collection_exists(self.collection):
            from llama_index.core import StorageContext

            self.index = VectorStoreIndex(
                nodes,
                embed_model=embed_model,
                storage_context=StorageContext.from_defaults(vector_store=store),
            )
        else:
            self.index = VectorStoreIndex.from_vector_store(store, embed_model=embed_model)
        self.retriever = self.index.as_retriever(similarity_top_k=top_k)

    def search(self, query: str) -> list[dict]:
        return [
            {**item.node.metadata, "text": item.node.get_content(), "score": item.score}
            for item in self.retriever.retrieve(query)
        ]

    def close(self):
        self.client.close()
