"""Initial schema — all tables including quarantine_locks.

Revision ID: 0001
Revises:
Create Date: 2026-06-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # tenants
    op.create_table(
        "tenants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(63), unique=True, nullable=False),
        sa.Column("plan", sa.String(31), default="free"),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("settings", postgresql.JSONB(), default=dict),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # skills
    op.create_table(
        "skills",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("slug", sa.String(127), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), default=""),
        sa.Column("version", sa.Integer(), default=1),
        sa.Column("status", sa.String(31), default="draft"),
        sa.Column("risk_level", sa.String(15), default="medium"),
        sa.Column("confidence_score", sa.Float(), default=0.0),
        sa.Column("definition", postgresql.JSONB(), default=dict),
        sa.Column("autonomy_level", sa.Integer(), default=0),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "slug", name="uq_skill_tenant_slug"),
    )
    op.create_index("ix_skill_tenant_status", "skills", ["tenant_id", "status"])

    # skill_versions
    op.create_table(
        "skill_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id"), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("definition", postgresql.JSONB(), default=dict),
        sa.Column("change_summary", sa.Text(), default=""),
        sa.Column("changed_by", sa.String(255), default="system"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_skill_version_skill", "skill_versions", ["skill_id", "version"])

    # workflow_runs
    op.create_table(
        "workflow_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id"), nullable=True),
        sa.Column("workflow_name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(31), default="pending"),
        sa.Column("trigger_type", sa.String(63), default="manual"),
        sa.Column("trigger_data", postgresql.JSONB(), default=dict),
        sa.Column("context_used", postgresql.JSONB(), default=dict),
        sa.Column("final_action", postgresql.JSONB(), nullable=True),
        sa.Column("critic_approved", sa.Boolean(), nullable=True),
        sa.Column("critic_risk_score", sa.Float(), nullable=True),
        sa.Column("critic_risk_level", sa.String(15), nullable=True),
        sa.Column("critic_reasons", postgresql.JSONB(), default=list),
        sa.Column("execution_result", postgresql.JSONB(), nullable=True),
        sa.Column("llm_cost_usd", sa.Float(), default=0.0),
        sa.Column("token_count", sa.Integer(), default=0),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_workflow_tenant_status", "workflow_runs", ["tenant_id", "status"])
    op.create_index("ix_workflow_tenant_created", "workflow_runs", ["tenant_id", "created_at"])

    # feedback_records
    op.create_table(
        "feedback_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("workflow_run_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("workflow_runs.id"), nullable=True),
        sa.Column("skill_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("skills.id"), nullable=True),
        sa.Column("feedback_type", sa.String(31), nullable=False),
        sa.Column("original_output", postgresql.JSONB(), default=dict),
        sa.Column("corrected_output", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.Text(), default=""),
        sa.Column("submitted_by", sa.String(255), nullable=False),
        sa.Column("submitted_by_role", sa.String(31), default="engineer"),
        sa.Column("processed", sa.Boolean(), default=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_tenant_created", "feedback_records", ["tenant_id", "created_at"])
    op.create_index("ix_feedback_skill", "feedback_records", ["skill_id"])

    # ingestion_cursors
    op.create_table(
        "ingestion_cursors",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("source_name", sa.String(63), nullable=False),
        sa.Column("cursor_value", sa.Text(), default=""),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("documents_synced", sa.Integer(), default=0),
        sa.Column("metadata", postgresql.JSONB(), default=dict),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("tenant_id", "source_name", name="uq_cursor_tenant_source"),
    )

    # quarantine_locks — Postgres source of truth for contradiction handshake
    op.create_table(
        "quarantine_locks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(63), nullable=False),
        sa.Column("skill_id", sa.String(127), nullable=False),
        sa.Column("pr_ref", sa.String(255), default=""),
        sa.Column("summary", sa.Text(), default=""),
        sa.Column("severity", sa.String(31), default="high"),
        sa.Column("locked_by", sa.String(127), default="contradiction-worker"),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "skill_id", name="uq_qlock_tenant_skill"),
    )
    op.create_index("ix_qlock_tenant", "quarantine_locks", ["tenant_id"])


def downgrade() -> None:
    op.drop_table("quarantine_locks")
    op.drop_table("ingestion_cursors")
    op.drop_table("feedback_records")
    op.drop_table("workflow_runs")
    op.drop_table("skill_versions")
    op.drop_table("skills")
    op.drop_table("tenants")
