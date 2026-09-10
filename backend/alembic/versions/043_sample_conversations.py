"""Sample conversations for Messages-Test draft context.

Revision ID: 043_sample_conversations
Revises: 042_drop_cs_router_tables
Create Date: 2026-09-10
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "043_sample_conversations"
down_revision: Union[str, None] = "042_drop_cs_router_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "sample_conversations" not in tables:
        op.create_table(
            "sample_conversations",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_sample_conversations_sort_order", "sample_conversations", ["sort_order"])
    if "sample_messages" not in tables:
        op.create_table(
            "sample_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("sample_conversations.id", ondelete="CASCADE"), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_sample_messages_conversation_id", "sample_messages", ["conversation_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "sample_messages" in tables:
        op.drop_table("sample_messages")
    if "sample_conversations" in tables:
        op.drop_table("sample_conversations")
