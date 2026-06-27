"""Zendesk connector + regex PII fallback (Presidio-optional)."""

from ingestion.base_connector import BaseConnector, ConnectorRegistry, _regex_redact
from ingestion.zendesk_connector import ZendeskConnector


# ── PII fallback (works without presidio installed) ──────────────────────────

def test_regex_redacts_common_pii():
    out = _regex_redact("Email a@b.com, call 415-555-1234, SSN 123-45-6789")
    assert "a@b.com" not in out
    assert "<EMAIL_ADDRESS>" in out and "<PHONE_NUMBER>" in out and "<US_SSN>" in out


def test_redact_pii_never_crashes_without_presidio():
    # In a lean env presidio isn't installed -> must fall back, not raise.
    assert BaseConnector.redact_pii("reach me at x@y.io") == "reach me at <EMAIL_ADDRESS>"
    assert BaseConnector.redact_pii("") == ""


# ── Connector ────────────────────────────────────────────────────────────────

def test_registered():
    assert "zendesk" in ConnectorRegistry.list_sources()
    assert ConnectorRegistry.get("zendesk") is ZendeskConnector


def test_normalize_ticket_redacts_and_tags():
    doc = ZendeskConnector().normalize({
        "_kind": "ticket",
        "id": 42,
        "subject": "Refund please",
        "description": "Customer email bob@acme.com wants a refund",
        "status": "open",
        "priority": "high",
        "tags": ["billing"],
        "requester_id": 7,
        "created_at": "2026-06-27T08:00:00Z",
    })
    assert doc.doc_type == "ticket"
    assert doc.id == "zendesk:ticket:42"
    assert doc.sensitivity_level == "confidential"
    assert "bob@acme.com" not in doc.content  # PII redacted
    assert doc.metadata["status"] == "open" and doc.metadata["tags"] == ["billing"]


def test_normalize_comment():
    doc = ZendeskConnector().normalize({
        "_kind": "ticket_comment",
        "id": 99,
        "_ticket_id": 42,
        "body": "We issued the refund.",
        "author_id": 3,
        "public": True,
        "created_at": "2026-06-27T09:00:00Z",
    })
    assert doc.doc_type == "ticket_comment"
    assert doc.metadata["ticket_id"] == 42 and doc.metadata["public"] is True
