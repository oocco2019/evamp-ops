"""Store OC GetStockMovement lines; drop snapshot history table.

Revision ID: 022_oc_stock_movement_line_drop_snapshot_history
Revises: 021_oc_sku_inventory_history
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "022_oc_stock_movement_line_drop_snapshot_history"
down_revision: Union[str, None] = "021_oc_sku_inventory_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "oc_stock_movement_line" not in tables:
        op.create_table(
            "oc_stock_movement_line",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("connection_id", sa.Integer(), nullable=False),
            sa.Column("mfskuid", sa.String(length=100), nullable=False),
            sa.Column("seller_skuid", sa.String(length=200), nullable=True),
            sa.Column("service_region", sa.String(length=64), nullable=False),
            sa.Column("inventory_status", sa.String(length=32), nullable=False),
            sa.Column("movement_id", sa.String(length=120), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("actual_count", sa.Integer(), nullable=True),
            sa.Column("reason", sa.String(length=500), nullable=True),
            sa.Column("order_number", sa.String(length=200), nullable=True),
            sa.Column("update_time_raw", sa.String(length=80), nullable=False),
            sa.Column("update_time_utc", sa.DateTime(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["connection_id"], ["oc_connections.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("connection_id", "movement_id", name="uq_oc_stock_mov_conn_movement"),
        )
        op.create_index("ix_oc_stock_movement_line_connection_id", "oc_stock_movement_line", ["connection_id"])
        op.create_index("ix_oc_stock_movement_line_mfskuid", "oc_stock_movement_line", ["mfskuid"])
        op.create_index("ix_oc_stock_movement_line_update_time_utc", "oc_stock_movement_line", ["update_time_utc"])

    if "oc_sku_inventory_history" in tables:
        idx_existing = {ix["name"] for ix in inspector.get_indexes("oc_sku_inventory_history")}
        for name in (
            "ix_oc_sku_inventory_history_conn_time",
            "ix_oc_sku_inventory_history_recorded_at",
            "ix_oc_sku_inventory_history_mfskuid",
        ):
            if name in idx_existing:
                op.drop_index(name, table_name="oc_sku_inventory_history")
        op.drop_table("oc_sku_inventory_history")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "oc_sku_inventory_history" not in tables:
        op.create_table(
            "oc_sku_inventory_history",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("connection_id", sa.Integer(), nullable=False),
            sa.Column("mfskuid", sa.String(length=100), nullable=False),
            sa.Column("service_region", sa.String(length=20), nullable=False),
            sa.Column("available", sa.Integer(), nullable=False),
            sa.Column("in_transit", sa.Integer(), nullable=False),
            sa.Column("received", sa.Integer(), nullable=False),
            sa.Column("reserved_allocated", sa.Integer(), nullable=False),
            sa.Column("reserved_hold", sa.Integer(), nullable=False),
            sa.Column("reserved_vas", sa.Integer(), nullable=False),
            sa.Column("suspend", sa.Integer(), nullable=False),
            sa.Column("unfulfillable", sa.Integer(), nullable=False),
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

    if "oc_stock_movement_line" in tables:
        op.drop_index("ix_oc_stock_movement_line_update_time_utc", table_name="oc_stock_movement_line")
        op.drop_index("ix_oc_stock_movement_line_mfskuid", table_name="oc_stock_movement_line")
        op.drop_index("ix_oc_stock_movement_line_connection_id", table_name="oc_stock_movement_line")
        op.drop_table("oc_stock_movement_line")
