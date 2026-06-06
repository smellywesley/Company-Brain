"""
Base agent interface for the Company Brain multi‑agent system.

All domain‑specific agents (CriticAgent, WorkflowAgent, etc.) extend
``BaseAgent`` and implement the ``run`` method.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.agents.llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)


@dataclass
class AgentResult:
    """Standardised result returned by every agent's ``run`` method."""

    success: bool
    output: dict[str, Any] = field(default_factory=dict)
    reasoning: str = ""
    audit_log: list[str] = field(default_factory=list)


class BaseAgent(ABC):
    """Abstract base for all Company Brain agents."""

    def __init__(
        self,
        name: str,
        description: str,
        llm: LLMAdapter,
        system_prompt: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.llm = llm
        self.system_prompt = system_prompt

    @abstractmethod
    async def run(self, input_data: dict[str, Any]) -> AgentResult:
        """Execute the agent's core logic and return a result."""
        ...

    async def get_context(self, query: str) -> list[dict[str, Any]]:
        """Query the vector store for relevant context.

        Default implementation returns an empty list. Override in
        subclasses that need RAG‑style retrieval.
        """
        logger.debug("Agent %s: get_context called (default – no vector store configured)", self.name)
        return []

    async def get_graph_context(self, query: str, tenant_id: str = "") -> list[dict[str, Any]]:
        """Query the knowledge graph for structured entity context.

        Returns entity neighbors from Neo4j. Falls back gracefully
        if Neo4j is unavailable.
        """
        if not tenant_id:
            return []

        try:
            from app.services.knowledge_graph.neo4j_store import Neo4jStore
            store = Neo4jStore()
            store.connect()
            results = store.search_entities(tenant_id, query, limit=10)
            # For each found entity, get its neighbors
            enriched: list[dict[str, Any]] = []
            for entity in results[:5]:  # Cap to prevent expensive queries
                neighbors = store.query_neighbors(tenant_id, entity["name"], depth=1)
                enriched.append({
                    "entity": entity,
                    "neighbors": neighbors[:10],
                })
            store.close()
            return enriched
        except Exception as exc:
            logger.warning("Agent %s: Knowledge graph unavailable: %s", self.name, exc)
            return []

    def _log(self, message: str) -> str:
        """Log a message and return it (for easy audit‑trail building)."""
        logger.info("Agent %s: %s", self.name, message)
        return f"[{self.name}] {message}"

