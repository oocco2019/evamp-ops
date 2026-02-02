"""message thread buyer_username and sync_metadata

Revision ID: 004_message_thread_buyer_and_sync_metadata
Revises: 003_add_order_buyer_username
Create Date: 2026-01-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_message_thread_buyer_and_sync_metadata"
down_revision: Union[str, None] = "003_add_order_buyer_username"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Alembic's default alembic_version.version_num is VARCHAR(32); our revision IDs are longer. Widen so UPDATE succeeds.
    op.execute(sa.text("ALTER TABLE alembic_version ALTER COLUMN version_num TYPE VARCHAR(128)"))
    # Idempotent: safe to re-run if a previous run failed partway (e.g. sync_metadata already exists)
    op.execute(sa.text("ALTER TABLE message_threads ADD COLUMN IF NOT EXISTS buyer_username VARCHAR(100)"))
    op.execute(sa.text(
        "CREATE TABLE IF NOT EXISTS sync_metadata ("
        "key VARCHAR(100) PRIMARY KEY, "
        "value TEXT NOT NULL, "
        "updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()"
        ")"
    ))


def downgrade() -> None:
    op.drop_table("sync_metadata")
    op.drop_column("message_threads", "buyer_username")
