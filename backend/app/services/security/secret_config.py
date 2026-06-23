"""
Centralised secret resolution with fail-closed production semantics.

Insecure or placeholder secrets must never reach production. In a production
environment (``ENVIRONMENT=production``/``prod``) a missing, placeholder, or
too-short secret raises at import/startup so the app refuses to boot. In
local/dev it falls back to an ephemeral per-process secret so the stack still
runs (tokens simply won't survive a restart — acceptable for local use).

This is the one place the "is this production?" decision and the placeholder
denylist live, so individual modules don't reinvent (and weaken) it.
"""

from __future__ import annotations

import logging
import os
import secrets as _secrets

logger = logging.getLogger("company_brain.security")

_PROD_ENVS = {"production", "prod"}

# Known shipped placeholders that must never be accepted as real secrets.
_PLACEHOLDERS = {
    "",
    "change-me",
    "change-me-in-production",
    "change-me-signing-key-minimum-32-chars",
    "dev",
    "test",
}


def is_production() -> bool:
    """True when running in a production environment."""
    return os.getenv("ENVIRONMENT", "local").strip().lower() in _PROD_ENVS


def require_secret(env_var: str, *, min_length: int = 16) -> str:
    """Return a strong secret from *env_var*.

    Fails closed in production when the value is missing, a known placeholder,
    or shorter than *min_length*. In dev/local, returns an ephemeral secret so
    the app still runs.
    """
    value = os.getenv(env_var, "")
    insecure = value in _PLACEHOLDERS or len(value) < min_length

    if not insecure:
        return value

    if is_production():
        raise RuntimeError(
            f"{env_var} must be set to a strong secret "
            f"(>= {min_length} chars, not a placeholder) in production. "
            f"Refusing to start."
        )

    logger.warning(
        "%s is unset/weak — using an ephemeral dev secret. "
        "Set %s before production (and for sessions stable across restarts).",
        env_var,
        env_var,
    )
    return _secrets.token_urlsafe(max(min_length, 32))
