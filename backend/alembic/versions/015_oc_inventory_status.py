"""Add OC connection and SKU mapping tables

Revision ID: 015_oc_inventory_status
Revises: 014_ebay_listing_sku_cache
Create Date: 2026-03-18
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "015_oc_inventory_status"
down_revision: Union[str, None] = "014_ebay_listing_sku_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oc_connections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("region", sa.String(length=10), nullable=False),
        sa.Column("environment", sa.String(length=10), nullable=False),
        sa.Column("oauth_base_url", sa.String(length=255), nullable=False),
        sa.Column("api_base_url", sa.String(length=255), nullable=False),
        sa.Column("signature_mode", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "oc_sku_mappings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("sku_code", sa.String(length=100), nullable=False),
        sa.Column("seller_skuid", sa.String(length=100), nullable=False),
        sa.Column("reference_skuid", sa.String(length=100), nullable=False),
        sa.Column("mfskuid", sa.String(length=100), nullable=False),
        sa.Column("service_region", sa.String(length=20), nullable=True),
        sa.Column("raw_payload", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["connection_id"], ["oc_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "sku_code", "mfskuid", name="uq_oc_mapping_conn_sku_mf"),
    )
    op.create_index("ix_oc_sku_mappings_sku_code", "oc_sku_mappings", ["sku_code"], unique=False)
    op.create_index("ix_oc_sku_mappings_mfskuid", "oc_sku_mappings", ["mfskuid"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_oc_sku_mappings_mfskuid", table_name="oc_sku_mappings")
    op.drop_index("ix_oc_sku_mappings_sku_code", table_name="oc_sku_mappings")
    op.drop_table("oc_sku_mappings")
    op.drop_table("oc_connections")
