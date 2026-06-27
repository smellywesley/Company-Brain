"""
Base connector interface for the Company Brain ingestion layer.

All source connectors (Slack, Notion, GitHub, etc.) extend ``BaseConnector``
and register themselves via the ``ConnectorRegistry``.
"""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── PII redaction (Presidio preferred, regex fallback) ───────────────────────
# Presidio + its spaCy model is heavy and not installed everywhere (the lean API
# image, dev boxes, CI). So it is imported LAZILY and, when unavailable, we fall
# back to a regex redactor — never crash on import, never silently ship PII. The
# ingestion/worker image installs presidio (requirements.txt) and gets the full
# engine; everything else degrades to regex. Sentinel values for the cache:
# None = not yet probed, False = unavailable, tuple = (analyzer, anonymizer).
_PII_ENGINES: Any = None

# Run most-specific patterns first so a 9-digit SSN / 16-digit card isn't eaten
# by the phone matcher. Tags mirror Presidio's entity labels for consistency.
_REGEX_PII: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "<US_SSN>"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "<CREDIT_CARD>"),
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<EMAIL_ADDRESS>"),
    (re.compile(r"(?:\+?\d{1,3}[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b"), "<PHONE_NUMBER>"),
]


def _get_pii_engines() -> Any:
    """Lazily build the Presidio engines once; cache False if unavailable."""
    global _PII_ENGINES
    if _PII_ENGINES is None:
        try:
            from presidio_analyzer import AnalyzerEngine
            from presidio_anonymizer import AnonymizerEngine

            _PII_ENGINES = (AnalyzerEngine(), AnonymizerEngine())
            logger.info("PII redaction: using Presidio engine")
        except Exception as exc:  # noqa: BLE001 — any import/init failure → fallback
            logger.warning(
                "PII redaction: Presidio unavailable (%s) — using regex fallback", exc
            )
            _PII_ENGINES = False
    return _PII_ENGINES


def _regex_redact(text: str) -> str:
    """Deterministic regex PII scrub (email, phone, SSN, card)."""
    for pattern, tag in _REGEX_PII:
        text = pattern.sub(tag, text)
    return text


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
        """Strip PII from *text* — Presidio when available, else regex fallback.

        Never raises: a redaction error must not abort ingestion, but it must
        also not leak, so on Presidio failure we still run the regex scrub.
        """
        if not text:
            return text
        engines = _get_pii_engines()
        if engines:
            analyzer, anonymizer = engines
            try:
                results = analyzer.analyze(text=text, language="en")
                if not results:
                    return text
                return anonymizer.anonymize(text=text, analyzer_results=results).text
            except Exception:  # noqa: BLE001
                logger.exception("Presidio redaction failed; using regex fallback")
        return _regex_redact(text)

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
