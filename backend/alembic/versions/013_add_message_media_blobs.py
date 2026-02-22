"""Add message_media_blobs table to store attachment bytes for retention after eBay purge

Revision ID: 013_message_media_blobs
Revises: 012_add_message_media
Create Date: 2026-02-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "013_message_media_blobs"
down_revision: Union[str, None] = "012_add_message_media"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.has_table(conn, "message_media_blobs"):
        return
    op.create_table(
        "message_media_blobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("message_id", sa.String(100), nullable=False),
        sa.Column("media_index", sa.Integer(), nullable=False),
        sa.Column("media_name", sa.String(255), nullable=True),
        sa.Column("media_type", sa.String(20), nullable=True),
        sa.Column("content_type", sa.String(100), nullable=True),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["message_id"], ["messages.message_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("message_id", "media_index", name="uq_message_media_blobs_message_index"),
    )
    op.create_index("ix_message_media_blobs_message_id", "message_media_blobs", ["message_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_message_media_blobs_message_id", table_name="message_media_blobs")
    op.drop_table("message_media_blobs")
