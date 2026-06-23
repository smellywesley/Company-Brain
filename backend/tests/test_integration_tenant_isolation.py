"""
Live-stack re-audit: the cross-tenant search leak (C1/C2).

This is the test that proves the fix actually holds against a real Weaviate —
it cannot be verified with mocks. Skipped unless WEAVIATE_URL points at a live
instance, so it stays green in CI/unit runs and becomes the gate for deploy.

Run with:  WEAVIATE_URL=http://localhost:8080 python -m pytest tests/test_integration_tenant_isolation.py
"""

import os
import time
import uuid

import pytest

pytest.importorskip("weaviate")

pytestmark = pytest.mark.skipif(
    not os.getenv("WEAVIATE_URL"),
    reason="live Weaviate required — set WEAVIATE_URL to run the tenant-isolation re-audit",
)

from ingestion.embedding_pipeline import WeaviateStore, DocumentChunk  # noqa: E402


def _chunk(tenant: str, text: str, vec: list[float]) -> DocumentChunk:
    return DocumentChunk(
        chunk_id=f"{tenant}-{uuid.uuid4()}",
        doc_id=str(uuid.uuid4()),
        content=text,
        source="itest",
        author="itest",
        timestamp="2026-01-01T00:00:00Z",
        sensitivity_level="low",
        doc_type="note",
        tenant_id=tenant,
        vector=vec,
    )


def test_search_does_not_leak_across_tenants():
    store = WeaviateStore()
    store.connect()
    try:
        ta = f"tenantA-{uuid.uuid4()}"
        tb = f"tenantB-{uuid.uuid4()}"
        va = [1.0, 0, 0, 0, 0, 0, 0, 0]
        vb = [0, 0, 0, 0, 0, 0, 0, 1.0]

        store.upsert_chunks([
            _chunk(ta, "SECRET-A confidential to tenant A", va),
            _chunk(tb, "SECRET-B confidential to tenant B", vb),
        ])
        time.sleep(1)  # allow async indexing

        # Tenant A queries with A's own vector — must see A, never B.
        res_a = store.search(query_vector=va, tenant_id=ta, limit=10)
        assert any("SECRET-A" in r["content"] for r in res_a)
        assert all("SECRET-B" not in r["content"] for r in res_a)

        # Tenant B issues the SAME query vector as A — must NOT see A's doc.
        res_b = store.search(query_vector=va, tenant_id=tb, limit=10)
        assert all("SECRET-A" not in r["content"] for r in res_b)

        # Empty tenant must fail closed (return nothing), never scan all tenants.
        assert store.search(query_vector=va, tenant_id="", limit=10) == []
    finally:
        store.close()
