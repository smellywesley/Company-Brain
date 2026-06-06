"""
Knowledge Graph Ingestion Hook.

Processes every ingested document through the entity extractor
and upserts the results into Neo4j. Designed to be called as
a post-ingestion hook in the embedding pipeline.
"""

from __future__ import annotations

import logging
from typing import Any

from app.services.knowledge_graph.entity_extractor import EntityExtractor
from app.services.knowledge_graph.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)


class KnowledgeGraphIngestionHook:
    """Post-ingestion hook that populates the knowledge graph."""

    def __init__(self, extractor: EntityExtractor, neo4j_store: Neo4jStore) -> None:
        self.extractor = extractor
        self.store = neo4j_store

    async def process_documents(
        self, tenant_id: str, documents: list[dict[str, Any]],
    ) -> int:
        """Extract entities from every document and upsert to Neo4j.

        Args:
            tenant_id: Tenant scope.
            documents: List of dicts with at least a 'content' or 'text' key.

        Returns:
            Count of entities created/updated.
        """
        entity_count = 0

        for i, doc in enumerate(documents):
            text = doc.get("content") or doc.get("text", "")
            if not text:
                continue

            try:
                result = await self.extractor.extract_with_relations(text)

                # Upsert entities
                for entity in result.entities:
                    props = {**entity.properties, "source": doc.get("source", "unknown")}
                    self.store.upsert_entity(
                        tenant_id=tenant_id,
                        name=entity.name,
                        entity_type=entity.entity_type,
                        properties=props,
                    )
                    entity_count += 1

                # Upsert relationships
                for rel in result.relationships:
                    self.store.upsert_relationship(
                        tenant_id=tenant_id,
                        source_name=rel.source_name,
                        target_name=rel.target_name,
                        rel_type=rel.relation_type,
                        properties=rel.properties,
                    )

            except Exception as exc:
                logger.error(
                    "KG Hook: Failed to process document %d/%d: %s",
                    i + 1, len(documents), exc,
                )
                # Continue processing remaining documents
                continue

            if (i + 1) % 10 == 0:
                logger.info("KG Hook: Processed %d/%d documents (%d entities)", i + 1, len(documents), entity_count)

        logger.info("KG Hook: Completed. %d entities created/updated from %d documents.", entity_count, len(documents))
        return entity_count
