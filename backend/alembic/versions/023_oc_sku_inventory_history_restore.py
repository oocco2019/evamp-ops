"""Restore append-only OC inventory snapshot history for stock cycle charts.

Revision ID: 023_oc_sku_inventory_history_restore
Revises: 022_oc_stock_movement_line_drop_snapshot_history
Create Date: 2026-04-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "023_oc_sku_inventory_history_restore"
down_revision: Union[str, None] = "022_oc_stock_movement_line_drop_snapshot_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "oc_sku_inventory_history" not in tables:
        op.create_table(
            "oc_sku_inventory_history",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("connection_id", sa.Integer(), nullable=False),
            sa.Column("mfskuid", sa.String(length=100), nullable=False),
            sa.Column("service_region", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("available", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("in_transit", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("received", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reserved_allocated", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reserved_hold", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("reserved_vas", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("suspend", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("unfulfillable", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("recorded_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["connection_id"], ["oc_connections.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_oc_sku_inventory_history_mfskuid", "oc_sku_inventory_history", ["mfskuid"])
        op.create_index("ix_oc_sku_inventory_history_recorded_at", "oc_sku_inventory_history", ["recorded_at"])
        op.create_index(
            "ix_oc_sku_inventory_history_conn_time",
            "oc_sku_inventory_history",
            ["connection_id", "recorded_at"],
        )
        op.create_index(
            "ix_oc_sku_inventory_history_conn_mf_region_time",
            "oc_sku_inventory_history",
            ["connection_id", "mfskuid", "service_region", "recorded_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "oc_sku_inventory_history" in tables:
        for name in (
            "ix_oc_sku_inventory_history_conn_mf_region_time",
            "ix_oc_sku_inventory_history_conn_time",
            "ix_oc_sku_inventory_history_recorded_at",
            "ix_oc_sku_inventory_history_mfskuid",
        ):
            idx = {ix["name"] for ix in inspector.get_indexes("oc_sku_inventory_history")}
            if name in idx:
                op.drop_index(name, table_name="oc_sku_inventory_history")
        op.drop_table("oc_sku_inventory_history")
