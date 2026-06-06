"""
Role-Based Access Control (RBAC) for Company Brain.

Loads policy definitions from a YAML configuration file and exposes helpers
to check and enforce permissions as FastAPI dependencies.

Usage:
    rbac = RBACPolicy()                         # loads default policies
    rbac = RBACPolicy("/path/to/policies.yaml")  # custom location

    @app.post("/ingest/{source}")
    async def ingest(source: str, _=Depends(rbac.require_permission("write", "ingestion"))):
        ...

OWASP considerations:
    - Deny-by-default: any action not explicitly listed is forbidden.
    - Roles and permissions are externalised in YAML for easy auditing.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

import yaml
from fastapi import Depends, HTTPException, Request

logger = logging.getLogger("company_brain.rbac")

_DEFAULT_POLICY_PATH = Path(__file__).parent / "rbac_policies.yaml"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class _ActionRule:
    """An action a role is allowed to perform, optionally scoped to resources."""

    name: str
    resources: Set[str] = field(default_factory=set)  # empty = all resources

    def covers_resource(self, resource: str) -> bool:
        """Return ``True`` if this rule applies to *resource*."""
        # An empty set means "all resources are allowed".
        if not self.resources:
            return True
        return resource in self.resources


@dataclass
class _RoleDefinition:
    """Internal representation of a role loaded from YAML."""

    name: str
    description: str = ""
    actions: Dict[str, _ActionRule] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Policy class
# ---------------------------------------------------------------------------

class RBACPolicy:
    """RBAC policy engine backed by a YAML configuration file.

    Parameters
    ----------
    policy_path:
        Filesystem path to the YAML policy file.  Defaults to the bundled
        ``rbac_policies.yaml`` shipped alongside this module.
    """

    def __init__(self, policy_path: Optional[str] = None) -> None:
        self._path = Path(policy_path) if policy_path else _DEFAULT_POLICY_PATH
        self._roles: Dict[str, _RoleDefinition] = {}
        self._default_role: str = "viewer"
        self._load()

    # ------------------------------------------------------------------
    # Loader
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Parse the YAML policy file and populate internal data structures."""
        if not self._path.exists():
            logger.error("RBAC policy file not found: %s", self._path)
            raise FileNotFoundError(f"RBAC policy file not found: {self._path}")

        with open(self._path, "r", encoding="utf-8") as fh:
            raw: Dict[str, Any] = yaml.safe_load(fh)

        self._default_role = raw.get("default_role", "viewer")

        for role_name, role_data in raw.get("roles", {}).items():
            actions: Dict[str, _ActionRule] = {}
            for action_name, action_data in (role_data.get("actions") or {}).items():
                resources_list: List[str] = (action_data or {}).get("resources", []) or []
                actions[action_name] = _ActionRule(
                    name=action_name,
                    resources=set(resources_list),
                )
            self._roles[role_name] = _RoleDefinition(
                name=role_name,
                description=role_data.get("description", ""),
                actions=actions,
            )

        logger.info(
            "RBAC policies loaded – %d roles from %s", len(self._roles), self._path
        )

    # ------------------------------------------------------------------
    # Permission check
    # ------------------------------------------------------------------

    def check_permission(self, user_role: str, action: str, resource: str) -> bool:
        """Check whether *user_role* is allowed to perform *action* on *resource*.

        Returns ``True`` if the role has an explicit grant for the action
        (optionally scoped to the resource).  Defaults to **deny**.

        Parameters
        ----------
        user_role:
            Role identifier (e.g. ``"admin"``, ``"viewer"``).
        action:
            Action identifier (e.g. ``"read"``, ``"write"``).
        resource:
            Resource identifier (e.g. ``"documents"``, ``"workflows"``).
        """
        role_def = self._roles.get(user_role)
        if role_def is None:
            logger.warning("Unknown role '%s' – denying access", user_role)
            return False

        action_rule = role_def.actions.get(action)
        if action_rule is None:
            return False

        return action_rule.covers_resource(resource)

    # ------------------------------------------------------------------
    # FastAPI dependency factory
    # ------------------------------------------------------------------

    def require_permission(
        self, action: str, resource: str
    ) -> Callable[..., None]:
        """Return a FastAPI dependency that raises ``403`` if the request
        user lacks the required permission.

        The dependency reads ``request.state.user`` (populated by
        :class:`~middleware.auth.OIDCAuthMiddleware`) and inspects the
        first role found in ``user.roles``, falling back to the configured
        default role.

        Parameters
        ----------
        action:
            Required action (e.g. ``"write"``).
        resource:
            Target resource (e.g. ``"documents"``).

        Returns
        -------
        Callable
            A FastAPI ``Depends``-compatible callable.
        """

        async def _dependency(request: Request) -> None:
            user = getattr(request.state, "user", None)
            if user is None:
                logger.warning(
                    "RBAC check without authenticated user on %s %s",
                    request.method,
                    request.url.path,
                )
                raise HTTPException(status_code=401, detail="Authentication required")

            # Determine effective role – first explicit role, then default
            user_role: str = (
                user.roles[0] if user.roles else self._default_role
            )

            if not self.check_permission(user_role, action, resource):
                logger.warning(
                    "RBAC denied: user=%s role=%s action=%s resource=%s",
                    user.sub,
                    user_role,
                    action,
                    resource,
                )
                raise HTTPException(
                    status_code=403,
                    detail=f"Insufficient permissions: '{action}' on '{resource}' requires a higher role",
                )

            logger.debug(
                "RBAC granted: user=%s role=%s action=%s resource=%s",
                user.sub,
                user_role,
                action,
                resource,
            )

        return _dependency

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    @property
    def default_role(self) -> str:
        """The default role applied when a user has no explicit role assignment."""
        return self._default_role

    @property
    def known_roles(self) -> List[str]:
        """List of role names loaded from the policy file."""
        return list(self._roles.keys())
