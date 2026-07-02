"""
Tests for the Tier 0 structural detector and the quarantine lock TTL.

The detector is pure (no I/O) so these run anywhere. The TTL tests inject a
fake Redis client so no live Redis is needed, matching the suite convention.
"""

from __future__ import annotations

from app.services.contradiction import detector
from app.services.quarantine import lock as quarantine


# ── Tier 0 detector ──────────────────────────────────────────────────────────

_PATCH_DELETE_TOKEN = """\
--- a/api/auth.py
+++ b/api/auth.py
@@ -10,7 +10,7 @@
-@app.post("/token")
-def issue_token(user):
+@app.post("/grpc/token")
+def issue_grpc_token(user):
"""


def test_detects_route_overlap():
    """PR removes POST /token; SOP step references /token -> overlap, high conf."""
    sop = "Step 2: call POST /token to obtain a bearer token before any request."
    result = detector.detect(["api/auth.py"], _PATCH_DELETE_TOKEN, sop)
    assert result["has_structural_overlap"] is True
    assert "/token" in result["matched_entities"]
    assert result["signal"]["confidence"] == 0.8  # route match is strong
    assert result["signal"]["source"] == "structural"


def test_no_overlap_when_sop_unrelated():
    """A PR touching auth must NOT flag an unrelated billing SOP."""
    sop = "Step 1: open the billing dashboard and export the monthly invoice CSV."
    result = detector.detect(["api/auth.py"], _PATCH_DELETE_TOKEN, sop)
    assert result["has_structural_overlap"] is False
    assert result["matched_entities"] == []
    assert result["signal"]["confidence"] == 0.0


def test_basename_match_is_weaker_than_route():
    """SOP referencing a changed file by name overlaps at lower confidence."""
    sop = "Our reconciliation logic lives in reconcile.py and runs nightly."
    result = detector.detect(["jobs/reconcile.py"], "", sop)
    assert result["has_structural_overlap"] is True
    assert "reconcile" in result["matched_entities"] or "reconcile.py" in result["matched_entities"]
    assert result["signal"]["confidence"] == 0.55


def test_word_boundary_prevents_substring_false_positive():
    """Entity 'token' must not match 'tokenizer' in unrelated SOP prose."""
    matched = detector.find_sop_overlap(
        "The tokenizer splits text into subwords.", {"token"}
    )
    assert matched == []


def test_generic_entities_filtered():
    """Short/stoplisted entities (api, id, main) never become signals."""
    ents = detector.extract_changed_entities(["src/main.py", "api/index.js"], "")
    assert "main" not in ents       # stoplisted
    assert "api" not in ents        # stoplisted
    assert "index" not in ents      # stoplisted


def test_only_changed_diff_lines_mined():
    """Context lines (no +/-) must not contribute entities."""
    patch = """\
@@ -1,3 +1,3 @@
 def context_only_helper():
-def removed_endpoint():
+def added_endpoint():
"""
    ents = detector.extract_changed_entities([], patch)
    assert "removed_endpoint" in ents
    assert "added_endpoint" in ents
    assert "context_only_helper" not in ents


def test_empty_inputs_are_safe():
    assert detector.detect([], "", "") == {
        "has_structural_overlap": False,
        "matched_entities": [],
        "signal": {
            "type": "structural_entity_overlap",
            "source": "structural",
            "confidence": 0.0,
            "detail": "no overlap between PR changes and SOP",
        },
    }


# ── Quarantine lock TTL ──────────────────────────────────────────────────────

class _FakeRedis:
    """Records set() calls so we can assert TTL without a live Redis."""

    def __init__(self):
        self.calls = []
        self.store = {}

    def set(self, key, value, ex=None):
        self.calls.append({"key": key, "value": value, "ex": ex})
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        return 1 if self.store.pop(key, None) is not None else 0


# These TTL tests exercise the Redis *cache* layer only, so they force the
# Redis-only dev path deterministically: _asyncpg=None makes the behavior
# identical whether or not asyncpg happens to be installed (in CI it is, and
# without this the tests would try to reach a real Postgres on localhost),
# and the env flag opts into the dev-only escape hatch explicitly. The
# production fail-closed semantics have their own tests in
# test_quarantine_lock_semantics.py.
def _redis_only(monkeypatch) -> "_FakeRedis":
    monkeypatch.setattr(quarantine, "_asyncpg", None)
    monkeypatch.setenv("QUARANTINE_LOCK_ALLOW_REDIS_ONLY_DEV", "true")
    fake = _FakeRedis()
    monkeypatch.setattr(quarantine, "_client", fake)
    return fake


def test_soft_lock_has_default_ttl(monkeypatch):
    """A normal quarantine self-heals: set() is called with ex=24h."""
    fake = _redis_only(monkeypatch)
    quarantine.acquire_sync("t1", "s1", pr_ref="PR #1", summary="x")
    assert fake.calls[0]["ex"] == quarantine._DEFAULT_TTL_SECONDS == 86_400


def test_permanent_lock_opt_in(monkeypatch):
    """ttl_seconds=None makes a permanent lock (no expiry) for confirmed cases."""
    fake = _redis_only(monkeypatch)
    quarantine.acquire_sync("t1", "s1", pr_ref="PR #1", summary="x", ttl_seconds=None)
    assert fake.calls[0]["ex"] is None


def test_custom_ttl_passthrough(monkeypatch):
    fake = _redis_only(monkeypatch)
    quarantine.acquire_sync("t1", "s1", pr_ref="PR #1", summary="x", ttl_seconds=3600)
    assert fake.calls[0]["ex"] == 3600
