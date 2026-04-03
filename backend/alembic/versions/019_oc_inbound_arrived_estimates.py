"""Persist rough arrived/putaway stage estimates for inbound orders

Revision ID: 019_oc_inbound_arrived_estimates
Revises: 018_orders_sales_channel
Create Date: 2026-04-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "019_oc_inbound_arrived_estimates"
down_revision: Union[str, None] = "018_orders_sales_channel"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oc_inbound_orders" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("oc_inbound_orders")}
    if "putaway_at" not in cols:
        op.add_column("oc_inbound_orders", sa.Column("putaway_at", sa.DateTime(), nullable=True))
    if "arrived_at" not in cols:
        op.add_column("oc_inbound_orders", sa.Column("arrived_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oc_inbound_orders" not in inspector.get_table_names():
        return

    cols = {c["name"] for c in inspector.get_columns("oc_inbound_orders")}
    if "arrived_at" in cols:
        op.drop_column("oc_inbound_orders", "arrived_at")
    if "putaway_at" in cols:
        op.drop_column("oc_inbound_orders", "putaway_at")

