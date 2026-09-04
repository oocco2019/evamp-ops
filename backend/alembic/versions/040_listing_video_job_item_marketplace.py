"""Add marketplace_id to listing_video_job_items.

Revision ID: 040_listing_video_job_item_marketplace
Revises: 039_listing_video_jobs
Create Date: 2026-09-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "040_listing_video_job_item_marketplace"
down_revision: Union[str, None] = "039_listing_video_jobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("listing_video_job_items")]
    if "marketplace_id" not in cols:
        op.add_column(
            "listing_video_job_items",
            sa.Column("marketplace_id", sa.String(20), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = [c["name"] for c in inspector.get_columns("listing_video_job_items")]
    if "marketplace_id" in cols:
        op.drop_column("listing_video_job_items", "marketplace_id")
