"""automations

Revision ID: 0007
Revises: 0006
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, Sequence[str], None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("sessions", sa.Column("purpose", sa.Text(), server_default="chat", nullable=False))
    op.create_table(
        "automations",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("task", sa.Text(), nullable=False),
        sa.Column("trigger_text", sa.Text(), nullable=False),
        sa.Column("trigger_kind", sa.Text(), nullable=False),
        sa.Column("trigger", JSONB, nullable=False),
        sa.Column("tools", JSONB, server_default="[]", nullable=False),
        sa.Column("locked", JSONB, server_default="{}", nullable=False),
        sa.Column("status", sa.Text(), server_default="active", nullable=False),
        sa.Column("status_reason", sa.Text(), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failure_streak", sa.Integer(), server_default="0", nullable=False),
        sa.Column("conversation_id", sa.UUID(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("status in ('active', 'paused', 'error')", name="ck_automations_status"),
        sa.CheckConstraint("trigger_kind in ('schedule', 'event', 'watch')", name="ck_automations_trigger_kind"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["sessions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_automations_status_next_run", "automations", ["status", "next_run_at"])
    op.create_table(
        "automation_runs",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("automation_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="running", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output", sa.Text(), nullable=True),
        sa.Column("tool_calls", JSONB, nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("event", JSONB, nullable=True),
        sa.Column("event_key", sa.Text(), nullable=True),
        sa.CheckConstraint("source in ('schedule', 'event', 'watch', 'test')", name="ck_automation_runs_source"),
        sa.CheckConstraint("status in ('running', 'succeeded', 'failed')", name="ck_automation_runs_status"),
        sa.ForeignKeyConstraint(["automation_id"], ["automations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("automation_id", "event_key", name="uq_automation_runs_event_key"),
    )
    op.create_index("ix_automation_runs_automation_id", "automation_runs", ["automation_id"])


def downgrade() -> None:
    op.drop_table("automation_runs")
    op.drop_table("automations")
    op.drop_column("sessions", "purpose")
