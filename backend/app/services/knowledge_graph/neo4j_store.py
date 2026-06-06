"""
Neo4j Store for the Knowledge Graph.

ALL Cypher queries use parameterized queries ($param syntax).
String interpolation is NEVER used for values.
All nodes include a tenant_id property for isolation.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


class Neo4jStore:
    """Production-grade Neo4j access layer with tenant isolation."""

    def __init__(self) -> None:
        self._driver = None

    def connect(self) -> None:
        """Connect to Neo4j using environment variables."""
        try:
            from neo4j import GraphDatabase
            uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
            user = os.getenv("NEO4J_USER", "neo4j")
            password = os.getenv("NEO4J_PASSWORD", "")
            self._driver = GraphDatabase.driver(uri, auth=(user, password))
            self._driver.verify_connectivity()
            logger.info("Neo4jStore: Connected to %s", uri)
        except Exception as exc:
            logger.error("Neo4jStore: Connection failed: %s", exc)
            self._driver = None

    def close(self) -> None:
        """Close the driver."""
        if self._driver:
            self._driver.close()
            self._driver = None

    def _ensure_connected(self) -> bool:
        if self._driver is None:
            logger.warning("Neo4jStore: Not connected.")
            return False
        return True

    # ── Upsert ──────────────────────────────────────────────────────────

    def upsert_entity(
        self, tenant_id: str, name: str, entity_type: str, properties: dict[str, Any] | None = None,
    ) -> str | None:
        """Create or update a node. Uses MERGE for deduplication.

        Labels are sanitized to alphanumeric to prevent injection.
        All values go through parameterized queries.
        """
        if not self._ensure_connected():
            return None

        safe_label = "".join(c for c in entity_type.title() if c.isalnum()) or "Entity"
        props = {**(properties or {}), "tenant_id": tenant_id, "name": name, "entity_type": entity_type}

        query = (
            f"MERGE (n:{safe_label} {{tenant_id: $tenant_id, name: $name}}) "
            "SET n += $props "
            "RETURN elementId(n) AS nid"
        )

        with self._driver.session() as session:
            result = session.run(query, tenant_id=tenant_id, name=name, props=props)
            record = result.single()
            return record["nid"] if record else None

    def upsert_relationship(
        self,
        tenant_id: str,
        source_name: str,
        target_name: str,
        rel_type: str,
        properties: dict[str, Any] | None = None,
    ) -> bool:
        """Create a relationship between two tenant-scoped nodes."""
        if not self._ensure_connected():
            return False

        safe_rel = "".join(c for c in rel_type.upper() if c.isalnum() or c == "_") or "RELATED_TO"

        query = (
            "MATCH (a {tenant_id: $tid, name: $src}) "
            "MATCH (b {tenant_id: $tid, name: $tgt}) "
            f"MERGE (a)-[r:{safe_rel}]->(b) "
            "SET r += $props "
            "RETURN type(r) AS rt"
        )

        with self._driver.session() as session:
            result = session.run(
                query, tid=tenant_id, src=source_name, tgt=target_name, props=properties or {},
            )
            return result.single() is not None

    # ── Query ───────────────────────────────────────────────────────────

    def query_entity(self, tenant_id: str, name: str) -> dict[str, Any] | None:
        """Find an entity by name within a tenant."""
        if not self._ensure_connected():
            return None

        query = (
            "MATCH (n {tenant_id: $tid, name: $name}) "
            "RETURN n.name AS name, labels(n) AS labels, properties(n) AS props"
        )
        with self._driver.session() as session:
            result = session.run(query, tid=tenant_id, name=name)
            record = result.single()
            if record:
                return {"name": record["name"], "labels": record["labels"], "properties": record["props"]}
            return None

    def query_neighbors(
        self, tenant_id: str, entity_name: str, depth: int = 1,
    ) -> list[dict[str, Any]]:
        """Get connected entities up to N hops."""
        if not self._ensure_connected():
            return []

        depth = min(depth, 3)
        query = (
            "MATCH (start {tenant_id: $tid, name: $name})"
            f"-[r*1..{depth}]-(neighbor) "
            "WHERE neighbor.tenant_id = $tid "
            "RETURN DISTINCT neighbor.name AS name, labels(neighbor) AS labels, "
            "properties(neighbor) AS props LIMIT 50"
        )

        with self._driver.session() as session:
            result = session.run(query, tid=tenant_id, name=entity_name)
            return [
                {"name": r["name"], "labels": r["labels"], "properties": r["props"]}
                for r in result
            ]

    def search_entities(
        self, tenant_id: str, query_text: str, limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Text search across entity names."""
        if not self._ensure_connected():
            return []

        cypher = (
            "MATCH (n) "
            "WHERE n.tenant_id = $tid AND toLower(n.name) CONTAINS toLower($q) "
            "RETURN n.name AS name, labels(n) AS labels, properties(n) AS props "
            "LIMIT $lim"
        )

        with self._driver.session() as session:
            result = session.run(cypher, tid=tenant_id, q=query_text, lim=limit)
            return [
                {"name": r["name"], "labels": r["labels"], "properties": r["props"]}
                for r in result
            ]

    def get_stats(self, tenant_id: str) -> dict[str, Any]:
        """Return node/relationship counts for a tenant."""
        if not self._ensure_connected():
            return {"nodes": 0, "relationships": 0, "types": {}}

        with self._driver.session() as session:
            nc = session.run(
                "MATCH (n) WHERE n.tenant_id = $tid RETURN count(n) AS c", tid=tenant_id,
            ).single()["c"]

            rc = session.run(
                "MATCH (a {tenant_id: $tid})-[r]->() RETURN count(r) AS c", tid=tenant_id,
            ).single()["c"]

            types_res = session.run(
                "MATCH (n) WHERE n.tenant_id = $tid "
                "UNWIND labels(n) AS lbl RETURN lbl, count(*) AS c ORDER BY c DESC",
                tid=tenant_id,
            )
            types = {r["lbl"]: r["c"] for r in types_res}

            return {"nodes": nc, "relationships": rc, "types": types}
