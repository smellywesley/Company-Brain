"""
LLM-based Entity Extraction for the Knowledge Graph.

Uses a cheap/fast LLM pass to extract entities and relationships
from every ingested document. Output is validated with Pydantic.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.agents.llm_adapter import LLMAdapter

logger = logging.getLogger(__name__)


# ── Data structures ─────────────────────────────────────────────────────────

@dataclass
class Entity:
    name: str
    entity_type: str  # person, project, tool, team, concept, process
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class Relationship:
    source_name: str
    target_name: str
    relation_type: str  # uses, owns, belongs_to, manages, depends_on, etc.
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExtractionResult:
    entities: list[Entity] = field(default_factory=list)
    relationships: list[Relationship] = field(default_factory=list)


# ── Pydantic validation models ─────────────────────────────────────────────

class EntityModel(BaseModel):
    name: str = Field(..., min_length=1)
    entity_type: str = Field(..., pattern="^(person|project|tool|team|concept|process)$")
    properties: dict[str, Any] = Field(default_factory=dict)


class RelationshipModel(BaseModel):
    source_name: str = Field(..., min_length=1)
    target_name: str = Field(..., min_length=1)
    relation_type: str = Field(..., min_length=1)
    properties: dict[str, Any] = Field(default_factory=dict)


class ExtractionResponse(BaseModel):
    entities: list[EntityModel] = Field(default_factory=list)
    relationships: list[RelationshipModel] = Field(default_factory=list)


# ── Prompt ──────────────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """
You are a Knowledge Graph entity extractor.
Given a document, extract named entities and their relationships.

Entity types: person, project, tool, team, concept, process

Return ONLY JSON matching this schema:
{
  "entities": [
    {"name": "String", "entity_type": "person|project|tool|team|concept|process", "properties": {}}
  ],
  "relationships": [
    {"source_name": "String", "target_name": "String", "relation_type": "String", "properties": {}}
  ]
}

Rules:
- Extract real named entities only, not generic nouns.
- Relationship types should be verbs: uses, manages, belongs_to, depends_on, created, owns.
- Keep entity names as they appear in the text (preserve capitalisation).
- If no entities are found, return empty lists.
"""


class EntityExtractor:
    """Extracts entities and relationships from text using a fast LLM."""

    def __init__(self, llm: LLMAdapter) -> None:
        self.llm = LLMAdapter(
            provider=llm.provider,
            api_key=llm.api_key,
            model=llm.model,
            temperature=0.0,
            max_tokens=500,
        )

    async def extract(self, text: str) -> list[Entity]:
        """Extract entities only (no relationships)."""
        result = await self.extract_with_relations(text)
        return result.entities

    async def extract_with_relations(self, text: str) -> ExtractionResult:
        """Extract entities and relationships from text."""
        if not text or len(text.strip()) < 20:
            return ExtractionResult()

        # Truncate to keep costs low
        snippet = text[:3000]

        try:
            response = await self.llm.generate(
                system_prompt=_EXTRACTION_PROMPT,
                user_prompt=f"## DOCUMENT\n{snippet}",
                retries=2,
            )

            raw = response.content.strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0]

            parsed = json.loads(raw)
            validated = ExtractionResponse(**parsed)

            entities = [
                Entity(name=e.name, entity_type=e.entity_type, properties=e.properties)
                for e in validated.entities
            ]
            relationships = [
                Relationship(
                    source_name=r.source_name,
                    target_name=r.target_name,
                    relation_type=r.relation_type,
                    properties=r.properties,
                )
                for r in validated.relationships
            ]

            return ExtractionResult(entities=entities, relationships=relationships)

        except json.JSONDecodeError as exc:
            logger.error("EntityExtractor: Invalid JSON from LLM: %s", exc)
            return ExtractionResult()
        except ValidationError as exc:
            logger.error("EntityExtractor: Pydantic validation failed: %s", exc)
            return ExtractionResult()
        except Exception as exc:
            logger.error("EntityExtractor: Extraction failed: %s", exc)
            return ExtractionResult()
