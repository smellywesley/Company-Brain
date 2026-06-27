"""
Action-executor registry (mirrors ingestion.ConnectorRegistry).

Executors are the final mile of the Governed Action loop: they run ONLY after
the CriticAgent approves and the skill isn't quarantined (docs/POSITIONING.md,
Governed Action pillar). The generic runner offers every registered executor to
the WorkflowAgent; an LLM-proposed ``action_type`` that matches one gets
executed, everything else is a dry-run.

Executor contract (keep new executors to this shape):

    @ExecutorRegistry.register("google_calendar_create_event")
    async def create_event(params: dict) -> dict:
        # params = the LLM action parameters + "_tenant_id" (str) injected by
        # the WorkflowAgent. Fetch per-tenant creds; never hardcode secrets:
        from app.services.security.secrets_service import SecretsService
        creds = SecretsService().get_tenant_credentials(UUID(params["_tenant_id"]), "google")
        if not creds:
            return {"status": "needs_connection", "provider": "google"}
        ... real httpx call (timeout!) ...
        return {"status": "succeeded", ...}   # or {"status": "error", "detail": ...}

Rules: read creds via SecretsService, return a structured status (never
fabricate a success), keep external calls timed-out. Don't bypass the loop —
executors do not re-check policy; the critic already did.
"""

from __future__ import annotations

import importlib
import logging
from typing import Any, Awaitable, Callable

logger = logging.getLogger(__name__)

ActionExecutor = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

# The one shared line when adding an executor: list its module so its
# @register decorator runs. The executor file stays otherwise self-contained.
_EXECUTOR_MODULES = [
    "app.services.executors.crm_calendar",
    "app.services.executors.accounting",
]


class ExecutorRegistry:
    """Maps action_type -> async executor."""

    _registry: dict[str, ActionExecutor] = {}

    @classmethod
    def register(cls, action_type: str) -> Callable[[ActionExecutor], ActionExecutor]:
        def deco(fn: ActionExecutor) -> ActionExecutor:
            cls._registry[action_type] = fn
            logger.debug("Registered executor: %s", action_type)
            return fn
        return deco

    @classmethod
    def build(cls) -> dict[str, ActionExecutor]:
        return dict(cls._registry)


def load_executors() -> dict[str, ActionExecutor]:
    """Import executor modules (so they self-register) and return the map.

    A module that fails to import (e.g. not built yet) is logged and skipped,
    not fatal — the loop just dry-runs that action_type.
    """
    for mod in _EXECUTOR_MODULES:
        try:
            importlib.import_module(mod)
        except Exception:  # noqa: BLE001
            logger.exception("Failed to import executor module %s", mod)
    return ExecutorRegistry.build()
