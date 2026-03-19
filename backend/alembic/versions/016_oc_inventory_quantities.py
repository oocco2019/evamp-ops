"""Add OC inventory quantities table

Revision ID: 016_oc_inventory_quantities
Revises: 015_oc_inventory_status
Create Date: 2026-03-19
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "016_oc_inventory_quantities"
down_revision: Union[str, None] = "015_oc_inventory_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oc_sku_inventory",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("connection_id", sa.Integer(), nullable=False),
        sa.Column("mfskuid", sa.String(length=100), nullable=False),
        sa.Column("service_region", sa.String(length=20), nullable=False),
        sa.Column("available", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("in_transit", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("received", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_allocated", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_hold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("reserved_vas", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("suspend", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unfulfillable", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("synced_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["connection_id"], ["oc_connections.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("connection_id", "mfskuid", "service_region", name="uq_oc_inventory_conn_mf_region"),
    )
    op.create_index("ix_oc_sku_inventory_mfskuid", "oc_sku_inventory", ["mfskuid"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_oc_sku_inventory_mfskuid", table_name="oc_sku_inventory")
    op.drop_table("oc_sku_inventory")
