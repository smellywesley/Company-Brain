"""
Embedding pipeline for Company Brain.

Takes normalised documents, chunks them into ≤512‑token windows with overlap,
generates dense vectors via sentence‑transformers, and upserts them into
Weaviate with full metadata.
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field
from typing import Any

import weaviate
from weaviate.classes.config import Configure, Property, DataType
from weaviate.classes.query import MetadataQuery

logger = logging.getLogger(__name__)

# ── Configuration ───────────────────────────────────────────────────────────
CHUNK_MAX_TOKENS = 512
CHUNK_OVERLAP_TOKENS = 64
EMBEDDING_MODEL = "all-MiniLM-L6-v2"
WEAVIATE_CLASS_NAME = "Document"


@dataclass
class DocumentChunk:
    """A single chunk of a larger document, ready for embedding."""

    chunk_id: str
    doc_id: str
    content: str
    source: str
    author: str
    timestamp: str
    sensitivity_level: str
    doc_type: str
    metadata: dict[str, Any] = field(default_factory=dict)
    vector: list[float] = field(default_factory=list)


# ── Chunker ─────────────────────────────────────────────────────────────────

def chunk_text(text: str, max_tokens: int = CHUNK_MAX_TOKENS, overlap: int = CHUNK_OVERLAP_TOKENS) -> list[str]:
    """Split *text* into overlapping windows of roughly *max_tokens* words.

    This uses a simple whitespace tokeniser. For production, swap in a
    proper tokeniser (e.g. tiktoken) without changing the interface.
    """
    words = text.split()
    if len(words) <= max_tokens:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(words):
        end = start + max_tokens
        chunks.append(" ".join(words[start:end]))
        start += max_tokens - overlap

    return chunks


# ── Embedder ────────────────────────────────────────────────────────────────

class Embedder:
    """Thin wrapper around sentence‑transformers for embedding generation."""

    def __init__(self, model_name: str = EMBEDDING_MODEL) -> None:
        # Lazy import so the heavy model is only loaded when needed
        from sentence_transformers import SentenceTransformer

        logger.info("Loading embedding model: %s", model_name)
        self._model = SentenceTransformer(model_name)
        self._dimension = self._model.get_sentence_embedding_dimension()
        logger.info("Embedding dimension: %d", self._dimension)

    @property
    def dimension(self) -> int:
        return self._dimension  # type: ignore[return-value]

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return a list of float vectors for the given texts."""
        vectors = self._model.encode(texts, show_progress_bar=False, normalize_embeddings=True)
        return [v.tolist() for v in vectors]


# ── Weaviate Store ──────────────────────────────────────────────────────────

class WeaviateStore:
    """Manages connection, schema, upsert, and search against Weaviate."""

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self._url = url or os.getenv("WEAVIATE_URL", "http://localhost:8080")
        self._api_key = api_key or os.getenv("WEAVIATE_API_KEY", "")
        self._client: weaviate.WeaviateClient | None = None

    # ── Connection ──────────────────────────────────────────────────────
    def connect(self) -> None:
        """Establish connection and ensure schema exists."""
        if self._api_key:
            self._client = weaviate.connect_to_custom(
                http_host=self._url.replace("http://", "").replace("https://", "").split(":")[0],
                http_port=int(self._url.split(":")[-1]) if ":" in self._url.split("//")[-1] else 8080,
                http_secure=self._url.startswith("https"),
                grpc_host=self._url.replace("http://", "").replace("https://", "").split(":")[0],
                grpc_port=50051,
                grpc_secure=self._url.startswith("https"),
                auth_credentials=weaviate.auth.AuthApiKey(self._api_key),
            )
        else:
            self._client = weaviate.connect_to_local()

        self._ensure_schema()
        logger.info("Connected to Weaviate at %s", self._url)

    def close(self) -> None:
        if self._client:
            self._client.close()

    def _ensure_schema(self) -> None:
        """Create the Document collection if it doesn't exist."""
        assert self._client is not None
        collections = self._client.collections

        if not collections.exists(WEAVIATE_CLASS_NAME):
            collections.create(
                name=WEAVIATE_CLASS_NAME,
                vectorizer_config=Configure.Vectorizer.none(),
                properties=[
                    Property(name="content", data_type=DataType.TEXT),
                    Property(name="source", data_type=DataType.TEXT),
                    Property(name="author", data_type=DataType.TEXT),
                    Property(name="timestamp", data_type=DataType.TEXT),
                    Property(name="sensitivity_level", data_type=DataType.TEXT),
                    Property(name="doc_type", data_type=DataType.TEXT),
                    Property(name="doc_id", data_type=DataType.TEXT),
                    Property(name="metadata_json", data_type=DataType.TEXT),
                ],
            )
            logger.info("Created Weaviate collection: %s", WEAVIATE_CLASS_NAME)

    # ── Upsert ──────────────────────────────────────────────────────────
    def upsert_chunks(self, chunks: list[DocumentChunk]) -> int:
        """Insert or update document chunks with their vectors."""
        assert self._client is not None
        import json

        collection = self._client.collections.get(WEAVIATE_CLASS_NAME)
        count = 0

        with collection.batch.dynamic() as batch:
            for chunk in chunks:
                batch.add_object(
                    properties={
                        "content": chunk.content,
                        "source": chunk.source,
                        "author": chunk.author,
                        "timestamp": chunk.timestamp,
                        "sensitivity_level": chunk.sensitivity_level,
                        "doc_type": chunk.doc_type,
                        "doc_id": chunk.doc_id,
                        "metadata_json": json.dumps(chunk.metadata),
                    },
                    vector=chunk.vector,
                    uuid=uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id),
                )
                count += 1

        logger.info("Upserted %d chunks to Weaviate", count)
        return count

    # ── Semantic search ─────────────────────────────────────────────────
    def search(
        self,
        query_vector: list[float],
        limit: int = 10,
        sensitivity_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return the top‑k nearest documents for *query_vector*."""
        assert self._client is not None
        import json

        collection = self._client.collections.get(WEAVIATE_CLASS_NAME)

        results = collection.query.near_vector(
            near_vector=query_vector,
            limit=limit,
            return_metadata=MetadataQuery(distance=True),
        )

        docs: list[dict[str, Any]] = []
        for obj in results.objects:
            props = obj.properties
            doc = {
                "content": props.get("content", ""),
                "source": props.get("source", ""),
                "author": props.get("author", ""),
                "timestamp": props.get("timestamp", ""),
                "sensitivity_level": props.get("sensitivity_level", ""),
                "doc_type": props.get("doc_type", ""),
                "doc_id": props.get("doc_id", ""),
                "metadata": json.loads(props.get("metadata_json", "{}")),
                "distance": obj.metadata.distance if obj.metadata else None,
            }
            if sensitivity_filter and doc["sensitivity_level"] != sensitivity_filter:
                continue
            docs.append(doc)

        return docs


# ── Pipeline orchestrator ───────────────────────────────────────────────────

class EmbeddingPipeline:
    """End‑to‑end pipeline: documents → chunks → embeddings → Weaviate."""

    def __init__(self, store: WeaviateStore | None = None, embedder: Embedder | None = None) -> None:
        self.store = store or WeaviateStore()
        self.embedder = embedder or Embedder()

    def run(self, documents: list[Any]) -> int:
        """Process a batch of ``NormalizedDocument`` objects.

        Returns the total number of chunks upserted.
        """
        self.store.connect()
        total = 0

        try:
            for doc in documents:
                text_chunks = chunk_text(doc.content)
                if not text_chunks:
                    continue

                vectors = self.embedder.embed(text_chunks)

                db_chunks: list[DocumentChunk] = []
                for idx, (text, vec) in enumerate(zip(text_chunks, vectors)):
                    db_chunks.append(
                        DocumentChunk(
                            chunk_id=f"{doc.source}:{doc.id}:{idx}",
                            doc_id=doc.id,
                            content=text,
                            source=doc.source,
                            author=doc.author,
                            timestamp=doc.timestamp,
                            sensitivity_level=doc.sensitivity_level,
                            doc_type=doc.doc_type,
                            metadata=doc.metadata,
                            vector=vec,
                        )
                    )

                total += self.store.upsert_chunks(db_chunks)

            logger.info("Pipeline complete: %d total chunks upserted", total)
        finally:
            self.store.close()

        return total
