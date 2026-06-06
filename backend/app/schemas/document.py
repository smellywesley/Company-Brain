"""
Pydantic models for documents and embeddings in Company Brain.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Any


class Document(BaseModel):
    """A normalised document from any ingestion source."""

    source: str = Field(..., description="Origin connector (slack, notion, github, etc.)")
    id: str = Field(..., description="Unique identifier within the source")
    author: str = Field(default="unknown")
    timestamp: str = Field(default="")
    content: str = Field(..., description="PII‑redacted text content")
    doc_type: str = Field(default="generic", description="message, page, issue, pr, readme, etc.")
    sensitivity_level: str = Field(default="internal", description="public | internal | confidential | restricted")
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentChunk(BaseModel):
    """A chunk of a document, ready for embedding storage."""

    chunk_id: str
    doc_id: str
    content: str
    source: str
    author: str = "unknown"
    timestamp: str = ""
    sensitivity_level: str = "internal"
    doc_type: str = "generic"
    metadata: dict[str, Any] = Field(default_factory=dict)
    vector: list[float] = Field(default_factory=list)


class EmbeddingResult(BaseModel):
    """Result of an embedding operation."""

    total_documents: int
    total_chunks: int
    chunks_upserted: int
    errors: list[str] = Field(default_factory=list)


class SearchQuery(BaseModel):
    """Incoming search request."""

    query: str = Field(..., min_length=1, description="Natural language search query")
    limit: int = Field(default=10, ge=1, le=100)
    sensitivity_filter: str | None = Field(default=None, description="Filter by sensitivity level")
    source_filter: str | None = Field(default=None, description="Filter by source connector")


class SearchResult(BaseModel):
    """A single search result with relevance metadata."""

    content: str
    source: str
    author: str
    timestamp: str
    sensitivity_level: str
    doc_type: str
    doc_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    distance: float | None = None
    relevance_score: float | None = None
