"""OC inbound orders cache table

Revision ID: 017_oc_inbound_orders_cache
Revises: 016_oc_inventory_quantities
Create Date: 2026-03-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "017_oc_inbound_orders_cache"
down_revision: Union[str, None] = "016_oc_inventory_quantities"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "oc_inbound_orders" not in inspector.get_table_names():
        op.create_table(
            "oc_inbound_orders",
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("connection_id", sa.Integer(), nullable=False),
            sa.Column("dedup_key", sa.String(length=320), nullable=False),
            sa.Column("seller_inbound_number", sa.String(length=200), nullable=False),
            sa.Column("oc_inbound_number", sa.String(length=200), nullable=True),
            sa.Column("status", sa.String(length=200), nullable=True),
            sa.Column("warehouse_code", sa.String(length=100), nullable=True),
            sa.Column("region", sa.String(length=20), nullable=True),
            sa.Column("shipping_method", sa.String(length=200), nullable=True),
            sa.Column("sku_qty", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("put_away_qty", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("inbound_at", sa.DateTime(), nullable=True),
            sa.Column("raw_payload", sa.Text(), nullable=True),
            sa.Column("synced_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.ForeignKeyConstraint(["connection_id"], ["oc_connections.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("connection_id", "dedup_key", name="uq_oc_inbound_conn_dedup"),
        )
        op.create_index("ix_oc_inbound_orders_connection_id", "oc_inbound_orders", ["connection_id"], unique=False)
        op.create_index("ix_oc_inbound_orders_status", "oc_inbound_orders", ["status"], unique=False)
    else:
        # Table already present (e.g. failed migration after CREATE committed). Ensure indexes exist.
        op.execute(
            sa.text(
                "CREATE INDEX IF NOT EXISTS ix_oc_inbound_orders_connection_id ON oc_inbound_orders (connection_id)"
            )
        )
        op.execute(
            sa.text("CREATE INDEX IF NOT EXISTS ix_oc_inbound_orders_status ON oc_inbound_orders (status)")
        )


def downgrade() -> None:
    op.execute(sa.text("DROP INDEX IF EXISTS ix_oc_inbound_orders_status"))
    op.execute(sa.text("DROP INDEX IF EXISTS ix_oc_inbound_orders_connection_id"))
    op.execute(sa.text("DROP TABLE IF EXISTS oc_inbound_orders"))
