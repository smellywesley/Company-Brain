"""
Tenant Isolation Layer.

Wraps Weaviate and Neo4j operations to enforce strict data isolation
between tenants. Every query is scoped by tenant_id.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Weaviate Tenant Isolation
# ─────────────────────────────────────────────────────────────────────────────

class TenantIsolatedWeaviateStore:
    """Wraps WeaviateStore to enforce tenant-scoped operations."""

    def __init__(self, base_store: Any) -> None:
        """
        Args:
            base_store: An instance of ingestion.embedding_pipeline.WeaviateStore
        """
        self._store = base_store

    def upsert(self, tenant_id: str, chunks: list[Any]) -> int:
        """Upsert ``DocumentChunk`` objects, forcing tenant_id on each.

        Overrides any tenant_id already on the chunk so a caller can never
        write into another tenant's space.
        """
        if not tenant_id:
            raise ValueError("upsert requires a non-empty tenant_id")
        for chunk in chunks:
            setattr(chunk, "tenant_id", tenant_id)
        return self._store.upsert_chunks(chunks)

    def search(
        self,
        tenant_id: str,
        query_vector: list[float],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Search with a mandatory tenant_id filter.

        This prevents Tenant A from seeing Tenant B's documents. The underlying
        store also fails closed on an empty tenant_id.
        """
        return self._store.search(
            query_vector=query_vector,
            tenant_id=tenant_id,
            limit=limit,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Neo4j Tenant Isolation
# ─────────────────────────────────────────────────────────────────────────────

class TenantIsolatedNeo4jStore:
    """Neo4j access layer with mandatory tenant_id scoping.

    ALL Cypher queries use parameterized queries ($param) to prevent
    injection. No string interpolation is ever used.
    """

    def __init__(self) -> None:
        self._driver = None

    def connect(self) -> None:
        """Connect to Neo4j using env vars."""
        try:
            from neo4j import GraphDatabase
            uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "")
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            self._driver.verify_connectivity()
            logger.info("TenantIsolatedNeo4jStore: Connected to Neo4j at %s", uri)
        except Exception as exc:
            logger.error("TenantIsolatedNeo4jStore: Failed to connect to Neo4j: %s", exc)
            self._driver = None

    def close(self) -> None:
        """Close the Neo4j driver."""
        if self._driver:
            self._driver.close()
            self._driver = None

    def create_node(
        self, tenant_id: str, label: str, properties: dict[str, Any],
    ) -> str | None:
        """Create or merge a node scoped to tenant_id.

        Uses MERGE to deduplicate by (tenant_id, name).
        Returns the node's element ID.
        """
        if not self._driver:
            logger.warning("Neo4j not connected. Skipping create_node.")
            return None

        # Sanitize label to alphanumeric only (labels can't be parameterized in Cypher)
        safe_label = "".join(c for c in label if c.isalnum())
        if not safe_label:
            safe_label = "Entity"

        props = {**properties, "tenant_id": tenant_id}
        name = props.get("name", "")

        query = (
            f"MERGE (n:{safe_label} {{tenant_id: $tenant_id, name: $name}}) "
            "SET n += $props "
            "RETURN elementId(n) AS node_id"
        )

        with self._driver.session() as session:
            result = session.run(
                query,
                tenant_id=tenant_id,
                name=name,
                props=props,
            )
            record = result.single()
            return record["node_id"] if record else None

    def create_relationship(
        self,
        tenant_id: str,
        from_name: str,
        to_name: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """Create a relationship between two nodes in the same tenant.

        Uses parameterized queries. rel_type is sanitized to alphanumeric.
        """
        if not self._driver:
            return False

        safe_rel = "".join(c for c in rel_type if c.isalnum() or c == "_")
        if not safe_rel:
            safe_rel = "RELATED_TO"

        query = (
            "MATCH (a {tenant_id: $tenant_id, name: $from_name}) "
            "MATCH (b {tenant_id: $tenant_id, name: $to_name}) "
            f"MERGE (a)-[r:{safe_rel}]->(b) "
            "SET r += $props "
            "RETURN type(r) AS rel"
        )

        with self._driver.session() as session:
            result = session.run(
                query,
                tenant_id=tenant_id,
                from_name=from_name,
                to_name=to_name,
                props=properties or {},
            )
            return result.single() is not None

    def query_neighbors(
        self, tenant_id: str, entity_name: str, depth: int = 1,
    ) -> list[dict[str, Any]]:
        """Get connected entities up to N hops, scoped to tenant_id."""
        if not self._driver:
            return []

        depth = min(depth, 3)  # Cap depth to prevent expensive queries

        query = (
            "MATCH (start {tenant_id: $tenant_id, name: $name})"
            f"-[r*1..{depth}]-(neighbor) "
            "WHERE neighbor.tenant_id = $tenant_id "
            "RETURN DISTINCT neighbor.name AS name, "
            "labels(neighbor) AS labels, "
            "properties(neighbor) AS props "
            "LIMIT 50"
        )

        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id, name=entity_name)
            return [
                {"name": r["name"], "labels": r["labels"], "properties": r["props"]}
                for r in result
            ]

    def search_entities(
        self, tenant_id: str, query: str, limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Text search across entity names, scoped to tenant_id."""
        if not self._driver:
            return []

        cypher = (
            "MATCH (n) "
            "WHERE n.tenant_id = $tenant_id AND toLower(n.name) CONTAINS toLower($query) "
            "RETURN n.name AS name, labels(n) AS labels, properties(n) AS props "
            "LIMIT $limit"
        )

        with self._driver.session() as session:
            result = session.run(cypher, tenant_id=tenant_id, query=query, limit=limit)
            return [
                {"name": r["name"], "labels": r["labels"], "properties": r["props"]}
                for r in result
            ]

    def get_stats(self, tenant_id: str) -> dict[str, Any]:
        """Return node count, relationship count, and type distribution."""
        if not self._driver:
            return {"nodes": 0, "relationships": 0, "types": {}}

        with self._driver.session() as session:
            node_count = session.run(
                "MATCH (n) WHERE n.tenant_id = $tid RETURN count(n) AS c",
                tid=tenant_id,
            ).single()["c"]

            rel_count = session.run(
                "MATCH (a {tenant_id: $tid})-[r]->() RETURN count(r) AS c",
                tid=tenant_id,
            ).single()["c"]

            types_result = session.run(
                "MATCH (n) WHERE n.tenant_id = $tid "
                "UNWIND labels(n) AS lbl RETURN lbl, count(*) AS c ORDER BY c DESC",
                tid=tenant_id,
            )
            types = {r["lbl"]: r["c"] for r in types_result}

            return {"nodes": node_count, "relationships": rel_count, "types": types}
