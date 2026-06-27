"""Offline unit tests for the integrations router's pure helpers.

No DB, no network, no auth — a full HTTP/route test would need the auth
middleware + DB and is the wrong level here.
"""

from app.routes.integrations import PROVIDER_ALLOWLIST, connected_providers


def test_allowlist_contents():
    assert {"slack", "notion", "github", "google", "hubspot", "quickbooks", "zendesk"} <= PROVIDER_ALLOWLIST
    assert "bogus" not in PROVIDER_ALLOWLIST


def test_connected_providers_only_counts_non_empty():
    result = connected_providers(
        {"google": {"access_token": "x"}, "slack": {}, "github": {"access_token": "y"}}
    )
    assert result == ["github", "google"]
