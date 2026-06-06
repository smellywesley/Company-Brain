"""
Notion connector for Company Brain.

Fetches databases and pages from the Notion API, converts block content
to Markdown, redacts PII, and normalises into the unified document schema.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from ingestion.base_connector import BaseConnector, ConnectorRegistry, NormalizedDocument

logger = logging.getLogger(__name__)

NOTION_API_VERSION = "2022-06-28"
NOTION_BASE_URL = "https://api.notion.com/v1"


@ConnectorRegistry.register
class NotionConnector(BaseConnector):
    """Pulls pages and databases from Notion."""

    SOURCE_NAME = "notion"

    def __init__(self) -> None:
        self._token: str = ""
        self._client: httpx.Client | None = None

    # ── Lifecycle ───────────────────────────────────────────────────────
    def authenticate(self) -> None:
        self._token = os.getenv("NOTION_API_KEY", "")
        if not self._token:
            raise EnvironmentError("NOTION_API_KEY environment variable is not set")
        self._client = httpx.Client(
            base_url=NOTION_BASE_URL,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Notion-Version": NOTION_API_VERSION,
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )
        logger.info("Notion connector authenticated")

    # ── Data fetching ───────────────────────────────────────────────────
    def fetch_raw(self) -> list[dict[str, Any]]:
        """Search for all pages the integration has access to."""
        assert self._client is not None, "Call authenticate() first"
        all_pages: list[dict[str, Any]] = []
        has_more = True
        start_cursor: str | None = None

        while has_more:
            body: dict[str, Any] = {"filter": {"value": "page", "property": "object"}, "page_size": 100}
            if start_cursor:
                body["start_cursor"] = start_cursor
            resp = self._client.post("/search", json=body)
            resp.raise_for_status()
            data = resp.json()
            all_pages.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        logger.info("Notion: fetched %d pages", len(all_pages))

        # Enrich each page with its block children (the actual content)
        for page in all_pages:
            page["_blocks"] = self._fetch_blocks(page["id"])

        return all_pages

    def _fetch_blocks(self, block_id: str) -> list[dict[str, Any]]:
        """Recursively fetch all block children for a page / block."""
        assert self._client is not None
        blocks: list[dict[str, Any]] = []
        has_more = True
        start_cursor: str | None = None

        while has_more:
            params: dict[str, Any] = {"page_size": 100}
            if start_cursor:
                params["start_cursor"] = start_cursor
            resp = self._client.get(f"/blocks/{block_id}/children", params=params)
            resp.raise_for_status()
            data = resp.json()
            for block in data.get("results", []):
                blocks.append(block)
                if block.get("has_children"):
                    block["_children"] = self._fetch_blocks(block["id"])
            has_more = data.get("has_more", False)
            start_cursor = data.get("next_cursor")

        return blocks

    # ── Normalisation ───────────────────────────────────────────────────
    def normalize(self, raw_item: dict[str, Any]) -> NormalizedDocument:
        page_id = raw_item["id"]
        title = self._extract_title(raw_item)
        markdown = self._blocks_to_markdown(raw_item.get("_blocks", []))
        full_text = f"# {title}\n\n{markdown}" if title else markdown

        created_by = raw_item.get("created_by", {}).get("id", "unknown")
        created_time = raw_item.get("created_time", "")

        return NormalizedDocument(
            source="notion",
            id=page_id,
            author=created_by,
            timestamp=created_time,
            content=self.redact_pii(full_text),
            doc_type="page",
            sensitivity_level="internal",
            metadata={
                "title": title,
                "url": raw_item.get("url", ""),
                "last_edited_time": raw_item.get("last_edited_time", ""),
                "parent_type": raw_item.get("parent", {}).get("type", ""),
            },
        )

    # ── Helpers ─────────────────────────────────────────────────────────
    @staticmethod
    def _extract_title(page: dict[str, Any]) -> str:
        props = page.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                parts = prop.get("title", [])
                return "".join(p.get("plain_text", "") for p in parts)
        return ""

    @classmethod
    def _blocks_to_markdown(cls, blocks: list[dict[str, Any]], depth: int = 0) -> str:
        """Convert a list of Notion blocks into Markdown."""
        lines: list[str] = []
        indent = "  " * depth

        for block in blocks:
            btype = block.get("type", "")
            data = block.get(btype, {})
            text = cls._rich_text_to_str(data.get("rich_text", []))

            if btype == "paragraph":
                lines.append(f"{indent}{text}")
            elif btype.startswith("heading_"):
                level = btype[-1]  # heading_1 → 1
                lines.append(f"{'#' * int(level)} {text}")
            elif btype == "bulleted_list_item":
                lines.append(f"{indent}- {text}")
            elif btype == "numbered_list_item":
                lines.append(f"{indent}1. {text}")
            elif btype == "to_do":
                checked = "x" if data.get("checked") else " "
                lines.append(f"{indent}- [{checked}] {text}")
            elif btype == "code":
                lang = data.get("language", "")
                lines.append(f"{indent}```{lang}\n{text}\n{indent}```")
            elif btype == "quote":
                lines.append(f"{indent}> {text}")
            elif btype == "callout":
                emoji = data.get("icon", {}).get("emoji", "💡")
                lines.append(f"{indent}> {emoji} {text}")
            elif btype == "divider":
                lines.append(f"{indent}---")
            elif btype == "toggle":
                lines.append(f"{indent}<details><summary>{text}</summary>")
            elif btype == "image":
                url = data.get("file", data.get("external", {})).get("url", "")
                caption = cls._rich_text_to_str(data.get("caption", []))
                lines.append(f"{indent}![{caption}]({url})")
            else:
                if text:
                    lines.append(f"{indent}{text}")

            # Recurse into children
            children = block.get("_children", [])
            if children:
                lines.append(cls._blocks_to_markdown(children, depth + 1))

        return "\n".join(lines)

    @staticmethod
    def _rich_text_to_str(rich_text: list[dict[str, Any]]) -> str:
        """Flatten Notion rich‑text array into a plain string."""
        return "".join(rt.get("plain_text", "") for rt in rich_text)
