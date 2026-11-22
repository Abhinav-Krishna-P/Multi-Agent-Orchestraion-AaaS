"""agent api: keys, settings, call log

Revision ID: 0008
Revises: 0007
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, Sequence[str], None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSONB = postgresql.JSONB(astext_type=sa.Text())


def upgrade() -> None:
    op.add_column("agents", sa.Column("api_actions", sa.Boolean(), server_default="true", nullable=False))
    op.add_column("agents", sa.Column("api_calls_per_minute", sa.Integer(), server_default="60", nullable=False))
    op.create_check_constraint("ck_agents_api_calls_per_minute", "agents", "api_calls_per_minute between 1 and 600")
    op.create_table(
        "agent_api_keys",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("hint", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash", name="uq_agent_api_keys_key_hash"),
    )
    op.create_index("ix_agent_api_keys_agent_id", "agent_api_keys", ["agent_id"])
    op.create_table(
        "api_calls",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("agent_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("key_id", sa.UUID(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), server_default="", nullable=False),
        sa.Column("tools_used", JSONB, server_default="[]", nullable=False),
        sa.Column("sources", JSONB, server_default="[]", nullable=False),
        sa.Column("outcome", sa.Text(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["key_id"], ["agent_api_keys.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_api_calls_agent_id_created_at", "api_calls", ["agent_id", "created_at"])


def downgrade() -> None:
    op.drop_table("api_calls")
    op.drop_table("agent_api_keys")
    op.drop_constraint("ck_agents_api_calls_per_minute", "agents")
    op.drop_column("agents", "api_calls_per_minute")
    op.drop_column("agents", "api_actions")
