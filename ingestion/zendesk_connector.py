"""
Zendesk ticketing connector (Support & Service role).

Fetches support tickets + their comments via the Zendesk REST API, redacts PII,
and normalises them into the unified document schema so the Support role can
answer with — and act on — real ticket history under governance.

Auth (API-token basic auth): ZENDESK_SUBDOMAIN + ZENDESK_EMAIL + ZENDESK_API_TOKEN.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any

import httpx

from ingestion.base_connector import BaseConnector, ConnectorRegistry, NormalizedDocument

logger = logging.getLogger(__name__)

# ponytail: simple offset caps instead of full backfill orchestration; raise the
# envs (or add incremental cursors) when a tenant outgrows them.
_MAX_TICKETS = int(os.getenv("ZENDESK_MAX_TICKETS", "500"))
_MAX_COMMENTS_PER_TICKET = int(os.getenv("ZENDESK_MAX_COMMENTS", "200"))


@ConnectorRegistry.register
class ZendeskConnector(BaseConnector):
    """Ingests Zendesk support tickets and their comments."""

    SOURCE_NAME = "zendesk"

    def __init__(self) -> None:
        self._client: httpx.Client | None = None
        self._subdomain: str = ""

    # ── Lifecycle ───────────────────────────────────────────────────────
    def authenticate(self) -> None:
        self._subdomain = os.getenv("ZENDESK_SUBDOMAIN", "")
        email = os.getenv("ZENDESK_EMAIL", "")
        token = os.getenv("ZENDESK_API_TOKEN", "")
        if not (self._subdomain and email and token):
            raise EnvironmentError(
                "ZENDESK_SUBDOMAIN, ZENDESK_EMAIL, and ZENDESK_API_TOKEN must be set"
            )
        creds = base64.b64encode(f"{email}/token:{token}".encode()).decode()
        self._client = httpx.Client(
            base_url=f"https://{self._subdomain}.zendesk.com/api/v2",
            headers={"Authorization": f"Basic {creds}", "Accept": "application/json"},
            timeout=30.0,
        )
        logger.info("ZendeskConnector: authenticated (subdomain=%s)", self._subdomain)

    # ── Data fetching ───────────────────────────────────────────────────
    def fetch_raw(self) -> list[dict[str, Any]]:
        assert self._client is not None, "Call authenticate() first"
        raw: list[dict[str, Any]] = []
        tickets = self._paginate("/tickets.json", key="tickets", cap=_MAX_TICKETS)
        logger.info("Zendesk: fetched %d tickets", len(tickets))
        for ticket in tickets:
            ticket["_kind"] = "ticket"
            raw.append(ticket)
            tid = ticket.get("id")
            if tid is None:
                continue
            for comment in self._paginate(
                f"/tickets/{tid}/comments.json", key="comments", cap=_MAX_COMMENTS_PER_TICKET
            ):
                comment["_kind"] = "ticket_comment"
                comment["_ticket_id"] = tid
                raw.append(comment)
        logger.info("Zendesk: fetched %d raw items", len(raw))
        return raw

    # ── Normalisation ───────────────────────────────────────────────────
    def normalize(self, raw_item: dict[str, Any]) -> NormalizedDocument:
        if raw_item.get("_kind") == "ticket_comment":
            return self._normalize_comment(raw_item)
        return self._normalize_ticket(raw_item)

    def _normalize_ticket(self, item: dict[str, Any]) -> NormalizedDocument:
        subject = item.get("subject", "") or ""
        description = item.get("description", "") or ""
        status = item.get("status", "")
        priority = item.get("priority") or "normal"
        tags = item.get("tags", []) or []
        url = (
            f"https://{self._subdomain}.zendesk.com/agent/tickets/{item.get('id')}"
            if self._subdomain else ""
        )
        return NormalizedDocument(
            source="zendesk",
            id=f"zendesk:ticket:{item.get('id')}",
            author=str(item.get("requester_id", "unknown")),
            timestamp=item.get("created_at", ""),
            content=self.redact_pii(f"## {subject}\n\n{description}\n\nStatus: {status} · Priority: {priority}"),
            doc_type="ticket",
            sensitivity_level="confidential",  # tickets carry customer data
            metadata={
                "ticket_id": item.get("id"),
                "status": status,
                "priority": priority,
                "tags": tags,
                "assignee_id": item.get("assignee_id"),
                "requester_id": item.get("requester_id"),
                "url": url,
                "updated_at": item.get("updated_at", ""),
            },
        )

    def _normalize_comment(self, item: dict[str, Any]) -> NormalizedDocument:
        body = item.get("body", "") or item.get("plain_body", "") or ""
        return NormalizedDocument(
            source="zendesk",
            id=f"zendesk:comment:{item.get('id')}",
            author=str(item.get("author_id", "unknown")),
            timestamp=item.get("created_at", ""),
            content=self.redact_pii(body),
            doc_type="ticket_comment",
            sensitivity_level="confidential",
            metadata={
                "ticket_id": item.get("_ticket_id"),
                "public": item.get("public", True),
                "author_id": item.get("author_id"),
            },
        )

    # ── Pagination ──────────────────────────────────────────────────────
    def _paginate(self, path: str, *, key: str, cap: int) -> list[dict[str, Any]]:
        """Follow Zendesk's ``next_page`` (absolute URL) pagination, up to ``cap``."""
        assert self._client is not None
        results: list[dict[str, Any]] = []
        url: str | None = path
        params: dict[str, Any] = {"per_page": 100}
        while url and len(results) < cap:
            resp = self._client.get(url, params=params)
            if resp.status_code == 404:
                break
            resp.raise_for_status()
            data = resp.json()
            results.extend(data.get(key, []))
            url = data.get("next_page")  # absolute URL or None
            params = {}  # next_page already encodes the query
        return results[:cap]
