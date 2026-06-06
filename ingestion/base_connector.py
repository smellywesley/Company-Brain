"""
Base connector interface for the Company Brain ingestion layer.

All source connectors (Slack, Notion, GitHub, etc.) extend ``BaseConnector``
and register themselves via the ``ConnectorRegistry``.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from presidio_analyzer import AnalyzerEngine
from presidio_anonymizer import AnonymizerEngine

logger = logging.getLogger(__name__)

# ── Shared PII engines (initialised once per process) ──────────────────────
_analyzer = AnalyzerEngine()
_anonymizer = AnonymizerEngine()


@dataclass
class NormalizedDocument:
    """Unified document schema used across all connectors."""

    source: str
    id: str
    author: str
    timestamp: str
    content: str  # PII‑redacted
    doc_type: str  # message, page, issue, pr, comment, etc.
    sensitivity_level: str = "internal"  # public | internal | confidential | restricted
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Abstract base class every ingestion connector must implement."""

    SOURCE_NAME: str = ""

    # ── Lifecycle ───────────────────────────────────────────────────────────
    @abstractmethod
    def authenticate(self) -> None:
        """Establish an authenticated session with the external service."""
        ...

    @abstractmethod
    def fetch_raw(self) -> list[dict[str, Any]]:
        """Pull raw records from the external service.

        Returns a list of provider‑native dicts (e.g. Slack message JSON).
        """
        ...

    @abstractmethod
    def normalize(self, raw_item: dict[str, Any]) -> NormalizedDocument:
        """Convert a single raw record into the unified schema."""
        ...

    # ── Shared helpers ──────────────────────────────────────────────────────
    @staticmethod
    def redact_pii(text: str) -> str:
        """Strip personally‑identifiable information from *text*."""
        if not text:
            return text
        results = _analyzer.analyze(text=text, language="en")
        if not results:
            return text
        anonymized = _anonymizer.anonymize(text=text, analyzer_results=results)
        return anonymized.text

    def ingest_all(self) -> list[NormalizedDocument]:
        """Full pipeline: authenticate → fetch → normalise → return."""
        logger.info("Connector %s: starting ingestion", self.SOURCE_NAME)
        self.authenticate()
        raw_items = self.fetch_raw()
        logger.info("Connector %s: fetched %d raw items", self.SOURCE_NAME, len(raw_items))
        docs: list[NormalizedDocument] = []
        for item in raw_items:
            try:
                docs.append(self.normalize(item))
            except Exception:
                logger.exception("Connector %s: failed to normalise item %s", self.SOURCE_NAME, item.get("id", "?"))
        logger.info("Connector %s: normalised %d documents", self.SOURCE_NAME, len(docs))
        return docs


# ── Registry ────────────────────────────────────────────────────────────────

class ConnectorRegistry:
    """Central registry that maps source names → connector classes."""

    _registry: dict[str, type[BaseConnector]] = {}

    @classmethod
    def register(cls, connector_class: type[BaseConnector]) -> type[BaseConnector]:
        """Decorator / direct call to register a connector."""
        name = connector_class.SOURCE_NAME
        if not name:
            raise ValueError(f"{connector_class.__name__} must set SOURCE_NAME")
        cls._registry[name] = connector_class
        logger.debug("Registered connector: %s", name)
        return connector_class

    @classmethod
    def get(cls, source_name: str) -> type[BaseConnector]:
        try:
            return cls._registry[source_name]
        except KeyError:
            raise KeyError(f"No connector registered for source '{source_name}'. Available: {list(cls._registry)}")

    @classmethod
    def list_sources(cls) -> list[str]:
        return list(cls._registry.keys())
