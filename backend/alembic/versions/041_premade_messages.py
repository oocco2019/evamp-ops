"""Add premade_messages for canned reply templates.

Revision ID: 041_premade_messages
Revises: 040_listing_video_job_item_marketplace
Create Date: 2026-09-09
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "041_premade_messages"
down_revision: Union[str, None] = "040_listing_video_job_item_marketplace"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "premade_messages" not in tables:
        op.create_table(
            "premade_messages",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_premade_messages_sort_order", "premade_messages", ["sort_order"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "premade_messages" in tables:
        op.drop_table("premade_messages")
