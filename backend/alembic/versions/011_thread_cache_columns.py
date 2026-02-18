"""Add cached last_message_preview, last_message_at, unread_count to message_threads

Revision ID: 011_thread_cache
Revises: 010_add_order_ad_fees
Create Date: 2026-02-18

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy import text

revision: str = "011_thread_cache"
down_revision: Union[str, None] = "010_add_order_ad_fees"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "message_threads",
        sa.Column("last_message_preview", sa.Text(), nullable=True),
    )
    op.add_column(
        "message_threads",
        sa.Column("last_message_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "message_threads",
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "message_threads",
        sa.Column("unread_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("""
        UPDATE message_threads t
        SET last_message_at = sub.last_at, unread_count = sub.uc, message_count = sub.mc
        FROM (
            SELECT
                thread_id,
                MAX(ebay_created_at) AS last_at,
                SUM(CASE WHEN is_read = false THEN 1 ELSE 0 END)::int AS uc,
                COUNT(*)::int AS mc
            FROM messages
            GROUP BY thread_id
        ) sub
        WHERE t.thread_id = sub.thread_id
    """)
    # Backfill last_message_preview in Python so we can sanitize invalid UTF-8 (e.g. BOM 0xef 0xbb) that would cause CharacterNotInRepertoireError in a raw SQL UPDATE
    conn = op.get_bind()
    thread_ids = [row[0] for row in conn.execute(text("SELECT thread_id FROM message_threads")).fetchall()]
    for tid in thread_ids:
        try:
            row = conn.execute(
                text("""
                    SELECT content FROM messages
                    WHERE thread_id = :tid
                    ORDER BY ebay_created_at DESC
                    LIMIT 1
                """),
                {"tid": tid},
            ).fetchone()
            if not row or not row[0]:
                continue
            raw = row[0]
            if isinstance(raw, str):
                preview = raw[:500].encode("utf-8", errors="replace").decode("utf-8")
            else:
                preview = raw.decode("utf-8", errors="replace")[:500] if raw else None
            if preview:
                conn.execute(
                    text("UPDATE message_threads SET last_message_preview = :p WHERE thread_id = :tid"),
                    {"p": preview, "tid": tid},
                )
        except Exception:
            # Driver can raise when decoding invalid UTF-8; leave last_message_preview NULL for this thread
            pass


def downgrade() -> None:
    op.drop_column("message_threads", "unread_count")
    op.drop_column("message_threads", "message_count")
    op.drop_column("message_threads", "last_message_at")
    op.drop_column("message_threads", "last_message_preview")
