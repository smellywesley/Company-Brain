"""
SQLAlchemy ORM models for Company Brain.

Every table includes a ``tenant_id`` column for multi-tenant isolation.
All timestamps are stored as UTC.

Tables:
    tenants            — Company / organisation registration
    skills             — Auto-discovered or human-seeded skill definitions
    skill_versions     — Version history for each skill (full JSON snapshot)
    workflow_runs      — Execution history for every workflow invocation
    feedback_records   — Human corrections to agent outputs
    ingestion_cursors  — Bookmark for incremental connector syncs
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _utcnow() -> datetime:
    """Return timezone-aware UTC now."""
    return datetime.now(timezone.utc)


def _uuid() -> uuid.UUID:
    """Generate a new UUID4."""
    return uuid.uuid4()


# ─────────────────────────────────────────────────────────────────────────────
# Tenants
# ─────────────────────────────────────────────────────────────────────────────

class Tenant(Base):
    """A company or organisation using the platform."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(63), unique=True, nullable=False)
    plan: Mapped[str] = mapped_column(String(31), default="free")  # free | pro | enterprise
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)  # LLM provider, limits, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    skills: Mapped[list["Skill"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    workflow_runs: Mapped[list["WorkflowRun"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    feedback_records: Mapped[list["FeedbackRecord"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


# ─────────────────────────────────────────────────────────────────────────────
# Skills
# ─────────────────────────────────────────────────────────────────────────────

class Skill(Base):
    """An auto-discovered or human-seeded operational skill.

    The ``definition`` JSONB column holds the full skill spec (steps,
    conditions, guardrails).  Each mutation creates a new ``SkillVersion``.
    """

    __tablename__ = "skills"
    __table_args__ = (
        UniqueConstraint("tenant_id", "slug", name="uq_skill_tenant_slug"),
        Index("ix_skill_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    slug: Mapped[str] = mapped_column(String(127), nullable=False)  # e.g. "refund-processing"
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(31), default="draft")  # draft | reviewed | active | deprecated | frozen

    # Risk classification for auto-activation logic
    risk_level: Mapped[str] = mapped_column(String(15), default="medium")  # low | medium | high
    confidence_score: Mapped[float] = mapped_column(Float, default=0.0)

    # The full skill definition (steps, conditions, guardrails)
    definition: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Provenance: where was this skill discovered from?
    discovered_from: Mapped[list] = mapped_column(JSONB, default=list)  # ["slack:#support", "notion:refund-policy"]
    created_by: Mapped[str] = mapped_column(String(255), default="system")  # "system" or user email

    # Cryptographic signature for tamper detection (HMAC-SHA256 of definition JSON)
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="skills")
    versions: Mapped[list["SkillVersion"]] = relationship(back_populates="skill", cascade="all, delete-orphan")


class SkillVersion(Base):
    """Immutable snapshot of a skill at a specific version.

    Created every time a skill's definition changes (via feedback,
    re-synthesis, or manual edit).  Enables full rollback.
    """

    __tablename__ = "skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version_number", name="uq_skill_version"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    skill_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    change_reason: Mapped[str] = mapped_column(Text, default="")  # Why was this version created?
    changed_by: Mapped[str] = mapped_column(String(255), default="system")
    signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    skill: Mapped["Skill"] = relationship(back_populates="versions")


# ─────────────────────────────────────────────────────────────────────────────
# Workflow Runs
# ─────────────────────────────────────────────────────────────────────────────

class WorkflowRun(Base):
    """Persistent record of every workflow execution.

    Stores the full input, output, critic verdict, and audit trail
    for compliance and learning purposes.
    """

    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_run_tenant_status", "tenant_id", "status"),
        Index("ix_workflow_run_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    workflow_name: Mapped[str] = mapped_column(String(127), nullable=False)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"), nullable=True)

    status: Mapped[str] = mapped_column(String(31), nullable=False)  # completed | rejected | pending_review | error
    trigger_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    context_used: Mapped[dict] = mapped_column(JSONB, default=dict)
    candidate_action: Mapped[dict] = mapped_column(JSONB, default=dict)
    final_action: Mapped[dict] = mapped_column(JSONB, default=dict)

    # Critic verdict
    critic_approved: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    critic_risk_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    critic_reasons: Mapped[list] = mapped_column(JSONB, default=list)

    # Execution metadata
    steps_executed: Mapped[list] = mapped_column(JSONB, default=list)
    audit_trail: Mapped[list] = mapped_column(JSONB, default=list)
    duration_ms: Mapped[float] = mapped_column(Float, default=0.0)
    llm_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)

    triggered_by: Mapped[str] = mapped_column(String(255), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="workflow_runs")
    feedback: Mapped[list["FeedbackRecord"]] = relationship(back_populates="workflow_run")


# ─────────────────────────────────────────────────────────────────────────────
# Feedback Records
# ─────────────────────────────────────────────────────────────────────────────

class FeedbackRecord(Base):
    """Human correction to an agent's output.

    Captures approve/reject/modify decisions, which drive skill
    re-synthesis and critic calibration.
    """

    __tablename__ = "feedback_records"
    __table_args__ = (
        Index("ix_feedback_tenant_created", "tenant_id", "created_at"),
        Index("ix_feedback_skill", "skill_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("workflow_runs.id"), nullable=True)
    skill_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("skills.id"), nullable=True)

    # Feedback type: approve | reject | modify | escalate | correct_skill
    feedback_type: Mapped[str] = mapped_column(String(31), nullable=False)

    # What the agent originally produced
    original_output: Mapped[dict] = mapped_column(JSONB, default=dict)

    # What the human corrected it to (for "modify" type)
    corrected_output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    # Human's reasoning
    reason: Mapped[str] = mapped_column(Text, default="")

    # Who submitted this feedback (OIDC user sub + email)
    submitted_by: Mapped[str] = mapped_column(String(255), nullable=False)
    submitted_by_role: Mapped[str] = mapped_column(String(31), default="engineer")

    # Processing status
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)

    # Relationships
    tenant: Mapped["Tenant"] = relationship(back_populates="feedback_records")
    workflow_run: Mapped["WorkflowRun | None"] = relationship(back_populates="feedback")


# ─────────────────────────────────────────────────────────────────────────────
# Ingestion Cursors
# ─────────────────────────────────────────────────────────────────────────────

class IngestionCursor(Base):
    """Bookmark for incremental connector syncs.

    Stores the last‑seen cursor / timestamp so connectors don't
    re-download everything on every run.
    """

    __tablename__ = "ingestion_cursors"
    __table_args__ = (
        UniqueConstraint("tenant_id", "source_name", name="uq_cursor_tenant_source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False)
    source_name: Mapped[str] = mapped_column(String(63), nullable=False)  # slack, notion, github
    cursor_value: Mapped[str] = mapped_column(Text, default="")  # Slack: next_cursor, GitHub: page/since, Notion: last_edited_time
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    documents_synced: Mapped[int] = mapped_column(Integer, default=0)
    # NOTE: the Python attribute is `extra_metadata` because `metadata` is a
    # reserved name on SQLAlchemy Declarative models (it shadows Base.metadata,
    # the MetaData registry, and raises InvalidRequestError at import time). The
    # DB column name stays "metadata" so the schema is unchanged.
    extra_metadata: Mapped[dict] = mapped_column("metadata", JSONB, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)
