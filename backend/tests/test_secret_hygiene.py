"""
Secret-hygiene regression gate.

secret_config._PLACEHOLDERS is the denylist require_secret() checks in
production. It must stay in sync with the placeholder-looking defaults we
actually ship in docker-compose.yml (`${VAR:-default}`) and .env.example —
otherwise a shipped dev default could one day flow through require_secret()
and be accepted as a "real" secret in production.

This file does NOT verify a live deployment's actual env vars are non
-placeholder (out of scope — that needs the live secret store). It only
pins: (1) every obviously-placeholder compose/env default is either in
_PLACEHOLDERS or explicitly allowlisted below with a reason, and (2)
require_secret() actually rejects every string in _PLACEHOLDERS in prod
and accepts them (with a warning) in dev.
"""

import re
from pathlib import Path

import pytest

from app.services.security import secret_config

_REPO_ROOT = Path(__file__).resolve().parents[2]

# Substrings that mark a compose/env default as "obviously meant to be
# replaced" rather than a real value (case-insensitive).
_PLACEHOLDER_MARKERS = (
    "change-me",
    "change-me-now",
    "dev-only",
    "your-token",
    "your-key",
)

# Compose-only infra secrets that go straight to their own container's env
# (Postgres/Redis/Weaviate/Neo4j) and never pass through Python
# require_secret() in the CURRENT architecture — so their placeholder
# defaults don't need to be in secret_config._PLACEHOLDERS today.
# IMPORTANT: if any of these vars are ever also read via require_secret()
# (e.g. a future app code path validates REDIS_PASSWORD itself), this
# allowlist must shrink and the value must move into _PLACEHOLDERS instead.
# Do not add new entries here without confirming the var is truly
# container-only — that's the whole point of this test.
_COMPOSE_ONLY_ALLOWLIST = {
    "change-me-in-production",  # POSTGRES_PASSWORD -> postgres container only
    "change-me",  # WEAVIATE_API_KEY -> weaviate container only
    "neo4j/change-me-now",  # NEO4J_AUTH "user/password" -> neo4j container only
}


def _compose_placeholder_defaults():
    """Extract every `${VAR:-default}` default from docker-compose.yml."""
    text = (_REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    return dict(re.findall(r"\$\{(\w+):-([^}]*)\}", text))


def test_compose_placeholder_defaults_are_tracked():
    defaults = _compose_placeholder_defaults()
    assert defaults, "sanity check: regex should find compose defaults"

    for var, default in defaults.items():
        looks_like_placeholder = any(m in default.lower() for m in _PLACEHOLDER_MARKERS)
        if not looks_like_placeholder:
            continue
        tracked = default in secret_config._PLACEHOLDERS or default in _COMPOSE_ONLY_ALLOWLIST
        assert tracked, (
            f"docker-compose.yml default for {var}={default!r} looks like a "
            f"placeholder but is neither in secret_config._PLACEHOLDERS nor in "
            f"the _COMPOSE_ONLY_ALLOWLIST in this test. Add it to one of them."
        )


@pytest.mark.parametrize("placeholder", sorted(secret_config._PLACEHOLDERS))
def test_all_placeholders_rejected_in_production(monkeypatch, placeholder):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("SOME_SECRET", placeholder)
    with pytest.raises(RuntimeError):
        secret_config.require_secret("SOME_SECRET", min_length=16)


@pytest.mark.parametrize("placeholder", sorted(secret_config._PLACEHOLDERS))
def test_all_placeholders_accepted_in_dev(monkeypatch, placeholder):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.setenv("SOME_SECRET", placeholder)
    val = secret_config.require_secret("SOME_SECRET", min_length=16)
    assert val and len(val) >= 16  # fails open to an ephemeral dev secret
