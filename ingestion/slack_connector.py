"""
Slack connector for Company Brain.

Extends ``BaseConnector`` to fetch messages from Slack channels via the
Slack Web API.  PII redaction is inherited from the base class.

Supports pagination via Slack's ``next_cursor`` mechanism.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ingestion.base_connector import BaseConnector, ConnectorRegistry, NormalizedDocument

logger = logging.getLogger(__name__)


@ConnectorRegistry.register
class SlackConnector(BaseConnector):
    """Ingests messages from Slack channels."""

    SOURCE_NAME = "slack"

    def __init__(self) -> None:
        self._token: str = ""
        self._client: httpx.Client | None = None

    # ── Lifecycle ───────────────────────────────────────────────────────

    def authenticate(self) -> None:
        """Load the Slack bot token and create an authenticated HTTP client."""
        self._token = os.getenv("SLACK_BOT_TOKEN", "")
        if not self._token:
            raise ValueError("SLACK_BOT_TOKEN environment variable is not set")

        self._client = httpx.Client(
            base_url="https://slack.com/api",
            headers={"Authorization": f"Bearer {self._token}"},
            timeout=30.0,
        )
        logger.info("SlackConnector: authenticated")

    def fetch_raw(self) -> list[dict[str, Any]]:
        """Fetch all messages from all accessible channels.

        Uses Slack's ``conversations.list`` + ``conversations.history``
        with cursor-based pagination.
        """
        assert self._client is not None, "Call authenticate() first"

        # 1. Fetch channel list
        channels = self._fetch_channels()
        logger.info("SlackConnector: found %d channels", len(channels))

        # 2. Fetch messages from each channel
        all_messages: list[dict[str, Any]] = []
        for channel in channels:
            channel_id = channel["id"]
            channel_name = channel.get("name", channel_id)
            messages = self._fetch_channel_messages(channel_id)
            # Tag each message with its channel for provenance
            for msg in messages:
                msg["_channel_id"] = channel_id
                msg["_channel_name"] = channel_name
            all_messages.extend(messages)
            logger.debug("SlackConnector: fetched %d messages from #%s", len(messages), channel_name)

        logger.info("SlackConnector: fetched %d total messages", len(all_messages))
        return all_messages

    def normalize(self, raw_item: dict[str, Any]) -> NormalizedDocument:
        """Convert a Slack message dict into a ``NormalizedDocument``."""
        text = raw_item.get("text", "")
        return NormalizedDocument(
            source="slack",
            id=f"slack:{raw_item.get('_channel_id', '')}:{raw_item.get('ts', '')}",
            author=raw_item.get("user", "unknown"),
            timestamp=raw_item.get("ts", ""),
            content=self.redact_pii(text),
            doc_type="message",
            sensitivity_level="internal",
            metadata={
                "channel_id": raw_item.get("_channel_id", ""),
                "channel_name": raw_item.get("_channel_name", ""),
                "thread_ts": raw_item.get("thread_ts"),
                "reactions": raw_item.get("reactions", []),
                "subtype": raw_item.get("subtype"),
            },
        )

    # ── Private helpers ─────────────────────────────────────────────────

    def _fetch_channels(self) -> list[dict[str, Any]]:
        """Paginate through ``conversations.list``."""
        assert self._client is not None
        channels: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"limit": 200, "types": "public_channel,private_channel"}
            if cursor:
                params["cursor"] = cursor

            resp = self._client.get("/conversations.list", params=params)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                logger.error("SlackConnector: conversations.list failed: %s", data.get("error"))
                break

            channels.extend(data.get("channels", []))
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return channels

    def _fetch_channel_messages(self, channel_id: str) -> list[dict[str, Any]]:
        """Paginate through ``conversations.history`` for a single channel."""
        assert self._client is not None
        messages: list[dict[str, Any]] = []
        cursor: str | None = None

        while True:
            params: dict[str, Any] = {"channel": channel_id, "limit": 200}
            if cursor:
                params["cursor"] = cursor

            resp = self._client.get("/conversations.history", params=params)
            resp.raise_for_status()
            data = resp.json()

            if not data.get("ok"):
                logger.warning(
                    "SlackConnector: conversations.history failed for %s: %s",
                    channel_id, data.get("error"),
                )
                break

            messages.extend(data.get("messages", []))
            cursor = data.get("response_metadata", {}).get("next_cursor")
            if not cursor:
                break

        return messages
