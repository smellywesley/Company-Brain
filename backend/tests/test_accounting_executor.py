"""Accounting executor tests — offline, no network, no new deps."""

from app.services.executors import accounting


class _FakeResp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code  # post_with_refresh checks this for the 401 path

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    """Stubs httpx.AsyncClient so no real HTTP happens."""

    def __init__(self, payload: dict, **_kw):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def post(self, *_a, **_kw):
        return _FakeResp(self._payload)


def _stub_creds(monkeypatch, creds: dict) -> None:
    monkeypatch.setattr(
        "app.services.executors.accounting.SecretsService.get_tenant_credentials",
        lambda self, tenant_id, integration: creds,
    )


def _stub_http(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(
        accounting.httpx, "AsyncClient", lambda **kw: _FakeClient(payload, **kw)
    )


_TENANT = "11111111-1111-1111-1111-111111111111"


# ── needs_connection ────────────────────────────────────────────────────
async def test_invoice_needs_connection(monkeypatch):
    _stub_creds(monkeypatch, {})
    out = await accounting.accounting_create_invoice(
        {"_tenant_id": _TENANT, "customer_id": "5", "amount": 100}
    )
    assert out == {"status": "needs_connection", "provider": "quickbooks"}


async def test_expense_needs_connection(monkeypatch):
    # Missing realm_id alone must still fail closed.
    _stub_creds(monkeypatch, {"access_token": "x"})
    out = await accounting.accounting_record_expense(
        {"_tenant_id": _TENANT, "amount": 50, "account_id": "7"}
    )
    assert out == {"status": "needs_connection", "provider": "quickbooks"}


# ── success path ─────────────────────────────────────────────────────────
async def test_invoice_succeeded(monkeypatch):
    _stub_creds(monkeypatch, {"access_token": "x", "realm_id": "123"})
    _stub_http(monkeypatch, {"Invoice": {"Id": "42", "DocNumber": "1001"}})
    out = await accounting.accounting_create_invoice(
        {"_tenant_id": _TENANT, "customer_id": "5", "amount": 100, "description": "Work"}
    )
    assert out["status"] == "succeeded"
    assert out["invoice_id"] == "42"


async def test_expense_succeeded(monkeypatch):
    _stub_creds(monkeypatch, {"access_token": "x", "realm_id": "123"})
    _stub_http(monkeypatch, {"Purchase": {"Id": "99"}})
    out = await accounting.accounting_record_expense(
        {"_tenant_id": _TENANT, "amount": 50, "account_id": "7", "description": "Lunch"}
    )
    assert out["status"] == "succeeded"
    assert out["purchase_id"] == "99"


# ── missing required param ───────────────────────────────────────────────
async def test_invoice_missing_customer():
    out = await accounting.accounting_create_invoice({"_tenant_id": _TENANT, "amount": 100})
    assert out["status"] == "error"
    assert "customer_id" in out["detail"]


async def test_expense_missing_account():
    out = await accounting.accounting_record_expense({"_tenant_id": _TENANT, "amount": 50})
    assert out["status"] == "error"
    assert "account_id" in out["detail"]
