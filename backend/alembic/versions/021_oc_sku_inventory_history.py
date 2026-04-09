"""Append-only OC inventory snapshot history for movement reporting

Revision ID: 021_oc_sku_inventory_history
Revises: 020_clear_inbound_stage_estimates_before_today
Create Date: 2026-04-05
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "021_oc_sku_inventory_history"
down_revision: Union[str, None] = "020_clear_inbound_stage_estimates_before_today"
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
            sa.Column("service_region", sa.String(length=20), nullable=False, server_default="UK"),
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
        inspector = sa.inspect(bind)

    idx_existing = {ix["name"] for ix in inspector.get_indexes("oc_sku_inventory_history")}
    if "ix_oc_sku_inventory_history_mfskuid" not in idx_existing:
        op.create_index("ix_oc_sku_inventory_history_mfskuid", "oc_sku_inventory_history", ["mfskuid"], unique=False)
    if "ix_oc_sku_inventory_history_recorded_at" not in idx_existing:
        op.create_index("ix_oc_sku_inventory_history_recorded_at", "oc_sku_inventory_history", ["recorded_at"], unique=False)
    if "ix_oc_sku_inventory_history_conn_time" not in idx_existing:
        op.create_index(
            "ix_oc_sku_inventory_history_conn_time",
            "oc_sku_inventory_history",
            ["connection_id", "recorded_at"],
            unique=False,
        )


def downgrade() -> None:
    op.drop_index("ix_oc_sku_inventory_history_conn_time", table_name="oc_sku_inventory_history")
    op.drop_index("ix_oc_sku_inventory_history_recorded_at", table_name="oc_sku_inventory_history")
    op.drop_index("ix_oc_sku_inventory_history_mfskuid", table_name="oc_sku_inventory_history")
    op.drop_table("oc_sku_inventory_history")
