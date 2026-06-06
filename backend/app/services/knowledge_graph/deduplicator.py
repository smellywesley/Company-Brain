"""
Entity Deduplicator for the Knowledge Graph.

Finds duplicate entities using heuristics (case-insensitive matching,
abbreviation expansion, substring matching) and merges them.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.services.knowledge_graph.neo4j_store import Neo4jStore

logger = logging.getLogger(__name__)

# Common abbreviation mappings
_ABBREVIATIONS: dict[str, str] = {
    "js": "javascript",
    "ts": "typescript",
    "py": "python",
    "k8s": "kubernetes",
    "pg": "postgresql",
    "db": "database",
    "api": "application programming interface",
    "ci": "continuous integration",
    "cd": "continuous deployment",
    "ml": "machine learning",
    "ai": "artificial intelligence",
    "fe": "frontend",
    "be": "backend",
    "qa": "quality assurance",
    "pr": "pull request",
    "ui": "user interface",
    "ux": "user experience",
}


@dataclass
class DuplicateGroup:
    canonical_name: str
    duplicates: list[str] = field(default_factory=list)
    confidence: float = 0.0


class EntityDeduplicator:
    """Finds and merges duplicate entities in the knowledge graph."""

    def find_duplicates(
        self, tenant_id: str, neo4j_store: Neo4jStore,
    ) -> list[DuplicateGroup]:
        """Scan all entities in a tenant and group duplicates."""
        all_entities = neo4j_store.search_entities(tenant_id, "", limit=1000)
        if not all_entities:
            return []

        names = [e["name"] for e in all_entities if e.get("name")]
        groups: list[DuplicateGroup] = []
        processed: set[str] = set()

        for i, name_a in enumerate(names):
            if name_a in processed:
                continue

            duplicates: list[str] = []
            for j, name_b in enumerate(names):
                if i == j or name_b in processed:
                    continue

                confidence = self._similarity(name_a, name_b)
                if confidence >= 0.8:
                    duplicates.append(name_b)

            if duplicates:
                # The longest name is likely the canonical form
                all_names = [name_a] + duplicates
                canonical = max(all_names, key=len)
                dupes = [n for n in all_names if n != canonical]

                groups.append(DuplicateGroup(
                    canonical_name=canonical,
                    duplicates=dupes,
                    confidence=0.85,
                ))
                processed.update(dupes)
                processed.add(name_a)

        logger.info("EntityDeduplicator: Found %d duplicate groups for tenant %s", len(groups), tenant_id)
        return groups

    def merge_duplicates(
        self, tenant_id: str, group: DuplicateGroup, neo4j_store: Neo4jStore,
    ) -> None:
        """Merge duplicate nodes into the canonical one.

        Repoints all relationships from duplicates to the canonical node,
        then deletes the duplicate nodes.
        """
        if not neo4j_store._driver:
            return

        for dup_name in group.duplicates:
            # Repoint incoming relationships
            query_in = (
                "MATCH (dup {tenant_id: $tid, name: $dup_name})<-[r]-(other) "
                "MATCH (canon {tenant_id: $tid, name: $canon_name}) "
                "WHERE other <> canon "
                "CREATE (canon)<-[r2:RELATED_TO]-(other) "
                "DELETE r"
            )
            # Repoint outgoing relationships
            query_out = (
                "MATCH (dup {tenant_id: $tid, name: $dup_name})-[r]->(other) "
                "MATCH (canon {tenant_id: $tid, name: $canon_name}) "
                "WHERE other <> canon "
                "CREATE (canon)-[r2:RELATED_TO]->(other) "
                "DELETE r"
            )
            # Delete the duplicate node
            query_del = (
                "MATCH (dup {tenant_id: $tid, name: $dup_name}) "
                "DETACH DELETE dup"
            )

            with neo4j_store._driver.session() as session:
                session.run(query_in, tid=tenant_id, dup_name=dup_name, canon_name=group.canonical_name)
                session.run(query_out, tid=tenant_id, dup_name=dup_name, canon_name=group.canonical_name)
                session.run(query_del, tid=tenant_id, dup_name=dup_name)

            logger.info("EntityDeduplicator: Merged '%s' into '%s'", dup_name, group.canonical_name)

    def _similarity(self, a: str, b: str) -> float:
        """Compute similarity between two entity names."""
        a_lower = a.lower().strip()
        b_lower = b.lower().strip()

        # Exact match (case-insensitive)
        if a_lower == b_lower:
            return 1.0

        # Abbreviation match
        if a_lower in _ABBREVIATIONS and _ABBREVIATIONS[a_lower] == b_lower:
            return 0.95
        if b_lower in _ABBREVIATIONS and _ABBREVIATIONS[b_lower] == a_lower:
            return 0.95

        # Pluralisation (checked before substring: a plural/singular pair is a
        # more precise relationship than a generic substring containment, so it
        # earns the higher score — e.g. "workflows"/"workflow" → 0.90, not 0.85)
        if a_lower.rstrip("s") == b_lower.rstrip("s") and len(a_lower) > 3:
            return 0.90

        # Substring match for longer names (> 5 chars)
        if len(a_lower) > 5 and len(b_lower) > 5:
            if a_lower in b_lower or b_lower in a_lower:
                return 0.85

        return 0.0
