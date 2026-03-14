"""Add ebay_listing_sku_cache for listing ID -> SKU lookup at scale

Revision ID: 014_ebay_listing_sku_cache
Revises: 013_message_media_blobs
Create Date: 2026-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "014_ebay_listing_sku_cache"
down_revision: Union[str, None] = "013_message_media_blobs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ebay_listing_sku_cache",
        sa.Column("listing_id", sa.String(32), nullable=False),
        sa.Column("sku", sa.String(100), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("listing_id"),
    )
    op.create_index("ix_ebay_listing_sku_cache_sku", "ebay_listing_sku_cache", ["sku"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_ebay_listing_sku_cache_sku", table_name="ebay_listing_sku_cache")
    op.drop_table("ebay_listing_sku_cache")
