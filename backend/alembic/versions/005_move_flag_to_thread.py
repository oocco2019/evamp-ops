"""Move is_flagged from messages to threads

Revision ID: 005_move_flag_to_thread
Revises: 004_message_thread_buyer_and_sync_metadata
Create Date: 2026-02-02
"""
from alembic import op
import sqlalchemy as sa

revision = "005_move_flag_to_thread"
down_revision = "004_message_thread_buyer_and_sync_metadata"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add is_flagged to message_threads
    op.add_column(
        "message_threads",
        sa.Column("is_flagged", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Copy flag status: if any message in thread was flagged, flag the thread
    op.execute("""
        UPDATE message_threads
        SET is_flagged = true
        WHERE thread_id IN (
            SELECT DISTINCT thread_id FROM messages WHERE is_flagged = true
        )
    """)
    # Drop is_flagged from messages
    op.drop_column("messages", "is_flagged")


def downgrade() -> None:
    # Add is_flagged back to messages
    op.add_column(
        "messages",
        sa.Column("is_flagged", sa.Boolean(), nullable=False, server_default="false"),
    )
    # Drop is_flagged from message_threads
    op.drop_column("message_threads", "is_flagged")
