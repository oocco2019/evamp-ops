"""Add media (attachments) to messages

Revision ID: 012_add_message_media
Revises: 011_thread_cache
Create Date: 2026-02-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "012_add_message_media"
down_revision: Union[str, None] = "011_thread_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column(
            "media",
            sa.JSON(),
            nullable=True,
            comment="Array of {mediaName, mediaType, mediaUrl} from eBay messageMedia",
        ),
    )


def downgrade() -> None:
    op.drop_column("messages", "media")
