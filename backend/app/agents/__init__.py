"""
Agent registry for Company Brain.

Maps agent names → classes so they can be discovered and instantiated
dynamically by the API layer.
"""

from __future__ import annotations

from typing import Type

from app.agents.base_agent import BaseAgent
from app.agents.critic_agent import CriticAgent
from app.agents.workflow_agent import WorkflowAgent


class AgentRegistry:
    """Central registry of all available agent types."""

    _registry: dict[str, Type[BaseAgent]] = {}

    @classmethod
    def register(cls, name: str, agent_class: Type[BaseAgent]) -> None:
        cls._registry[name] = agent_class

    @classmethod
    def get(cls, name: str) -> Type[BaseAgent]:
        try:
            return cls._registry[name]
        except KeyError:
            raise KeyError(f"No agent registered as '{name}'. Available: {list(cls._registry)}")

    @classmethod
    def list_agents(cls) -> list[str]:
        return list(cls._registry.keys())


# ── Auto‑register built‑in agents ──────────────────────────────────────────
AgentRegistry.register("critic", CriticAgent)
AgentRegistry.register("workflow", WorkflowAgent)
