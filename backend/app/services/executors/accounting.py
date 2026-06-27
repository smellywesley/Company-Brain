"""
Accounting executors (final mile of the Governed Action loop, Finance role).

These run ONLY after the CriticAgent approves (docs/POSITIONING.md, Governed
Action pillar). Finance is HIGH-trust, so be conservative: validate required
params, never fabricate a success, and surface a missing connection rather than
guessing. Per-tenant creds come from SecretsService.

Provider: QuickBooks Online ("quickbooks"). Creds carry "access_token" +
"realm_id". Plain httpx — no vendor SDKs. ponytail: no retries/backoff; one
timed call per action. Add backoff here if QBO's 429s start hurting.
"""

from __future__ import annotations

from uuid import UUID

import httpx

from app.services.executors.registry import ExecutorRegistry
from app.services.security.secrets_service import SecretsService

_TIMEOUT = 30.0
_BASE = "https://quickbooks.api.intuit.com/v3/company"


def _qbo_creds(tenant_id: str) -> tuple[str | None, str | None]:
    creds = SecretsService().get_tenant_credentials(UUID(tenant_id), "quickbooks") or {}
    return creds.get("access_token"), creds.get("realm_id")


@ExecutorRegistry.register("accounting_create_invoice")
async def accounting_create_invoice(params: dict) -> dict:
    """Create a QuickBooks Online invoice."""
    if not params.get("customer_id"):
        return {"status": "error", "detail": "missing customer_id"}

    # Accept either an explicit line_items list or a single amount+description.
    line_items = params.get("line_items")
    if not line_items:
        if params.get("amount") is None:
            return {"status": "error", "detail": "missing line_items or amount"}
        line_items = [{"amount": params["amount"], "description": params.get("description", "")}]

    token, realm_id = _qbo_creds(params["_tenant_id"])
    if not (token and realm_id):
        return {"status": "needs_connection", "provider": "quickbooks"}

    currency = params.get("currency", "USD")
    lines = []
    for item in line_items:
        line: dict = {
            "Amount": item["amount"],
            "DetailType": "SalesItemLineDetail",
            "SalesItemLineDetail": {},
        }
        if item.get("description"):
            line["Description"] = item["description"]
        lines.append(line)

    body: dict = {
        "CustomerRef": {"value": str(params["customer_id"])},
        "CurrencyRef": {"value": currency},
        "Line": lines,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_BASE}/{realm_id}/invoice",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        return {"status": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}

    invoice = data.get("Invoice", {})
    return {
        "status": "succeeded",
        "invoice_id": invoice.get("Id"),
        "doc_number": invoice.get("DocNumber"),
    }


@ExecutorRegistry.register("accounting_record_expense")
async def accounting_record_expense(params: dict) -> dict:
    """Record a QuickBooks Online expense (Purchase)."""
    if params.get("amount") is None:
        return {"status": "error", "detail": "missing amount"}
    if not params.get("account_id"):
        return {"status": "error", "detail": "missing account_id"}

    token, realm_id = _qbo_creds(params["_tenant_id"])
    if not (token and realm_id):
        return {"status": "needs_connection", "provider": "quickbooks"}

    payment_type = params.get("payment_type", "Cash")
    line: dict = {
        "Amount": params["amount"],
        "DetailType": "AccountBasedExpenseLineDetail",
        "AccountBasedExpenseLineDetail": {
            "AccountRef": {"value": str(params["account_id"])},
        },
    }
    if params.get("description"):
        line["Description"] = params["description"]

    body: dict = {
        "PaymentType": payment_type,
        "AccountRef": {"value": str(params["account_id"])},
        "Line": [line],
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                f"{_BASE}/{realm_id}/purchase",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                json=body,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPError as exc:
        return {"status": "error", "detail": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "detail": str(exc)}

    purchase = data.get("Purchase", {})
    return {
        "status": "succeeded",
        "purchase_id": purchase.get("Id"),
    }
