"""
Unit-level tenant-isolation regression for Weaviate search.

Isolation here is *property-filter* based (single ``Document`` collection scoped
by a mandatory ``tenant_id`` filter), NOT native Weaviate multi-tenancy. These
tests prove the filter is ALWAYS applied with the caller's tenant and that a
mock backend honoring that filter never returns another tenant's rows. The live
end-to-end proof against a real Weaviate is test_integration_tenant_isolation.py.
"""

from __future__ import annotations

import pytest

pytest.importorskip("weaviate")

from ingestion.embedding_pipeline import WeaviateStore  # noqa: E402


class _FakeMetadata:
    def __init__(self, distance=0.1):
        self.distance = distance


class _FakeObj:
    def __init__(self, props):
        self.properties = props
        self.metadata = _FakeMetadata()


class _FakeResult:
    def __init__(self, objects):
        self.objects = objects


class _FakeQuery:
    """Records the filter passed and honors it like Weaviate would."""

    def __init__(self, rows):
        self._rows = rows
        self.last_filter = None

    def near_vector(self, near_vector, limit, filters, return_metadata):
        self.last_filter = filters
        wanted = filters.value  # _FilterValue(value=<tenant>, target='tenant_id')
        matched = [_FakeObj(r) for r in self._rows if r["tenant_id"] == wanted]
        return _FakeResult(matched[:limit])


class _FakeCollection:
    def __init__(self, rows):
        self.query = _FakeQuery(rows)


class _FakeClient:
    def __init__(self, rows):
        self._collection = _FakeCollection(rows)

    class _Collections:
        def __init__(self, collection):
            self._c = collection

        def get(self, _name):
            return self._c

    @property
    def collections(self):
        return _FakeClient._Collections(self._collection)


_ROWS = [
    {"tenant_id": "A", "content": "SECRET-A", "source": "s", "author": "a",
     "timestamp": "t", "sensitivity_level": "low", "doc_type": "note", "doc_id": "1", "metadata_json": "{}"},
    {"tenant_id": "B", "content": "SECRET-B", "source": "s", "author": "a",
     "timestamp": "t", "sensitivity_level": "low", "doc_type": "note", "doc_id": "2", "metadata_json": "{}"},
]


def _store_with_rows():
    store = WeaviateStore()
    store._client = _FakeClient(_ROWS)  # inject fake, skip connect()
    return store


def test_search_applies_callers_tenant_filter():
    store = _store_with_rows()
    res = store.search(query_vector=[1, 0, 0], tenant_id="A", limit=10)
    # Filter targeted tenant_id == "A"
    flt = store._client._collection.query.last_filter
    assert flt.target == "tenant_id" and flt.value == "A"
    # Only A's row comes back
    assert [r["content"] for r in res] == ["SECRET-A"]


def test_tenant_b_query_cannot_see_tenant_a_rows():
    store = _store_with_rows()
    res = store.search(query_vector=[1, 0, 0], tenant_id="B", limit=10)
    assert all("SECRET-A" not in r["content"] for r in res)
    assert [r["content"] for r in res] == ["SECRET-B"]


def test_empty_tenant_fails_closed_without_querying():
    store = _store_with_rows()
    res = store.search(query_vector=[1, 0, 0], tenant_id="", limit=10)
    assert res == []
    # The query was never issued (fail closed before hitting the backend).
    assert store._client._collection.query.last_filter is None


def test_search_signature_requires_tenant_id():
    """tenant_id is a required parameter — a route cannot omit it by accident."""
    import inspect

    sig = inspect.signature(WeaviateStore.search)
    assert sig.parameters["tenant_id"].default is inspect.Parameter.empty
