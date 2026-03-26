"""orders: sales_channel for eBay vs Shopify (composite unique with external id)

Revision ID: 018_orders_sales_channel
Revises: 017_oc_inbound_orders_cache
Create Date: 2026-03-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "018_orders_sales_channel"
down_revision: Union[str, None] = "017_oc_inbound_orders_cache"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "sales_channel",
            sa.String(length=20),
            nullable=False,
            server_default="ebay",
        ),
    )
    op.drop_constraint("uq_ebay_order_id", "orders", type_="unique")
    op.create_unique_constraint(
        "uq_orders_sales_channel_ebay_order_id",
        "orders",
        ["sales_channel", "ebay_order_id"],
    )
    op.alter_column("orders", "sales_channel", server_default=None)


def downgrade() -> None:
    op.drop_constraint("uq_orders_sales_channel_ebay_order_id", "orders", type_="unique")
    op.create_unique_constraint("uq_ebay_order_id", "orders", ["ebay_order_id"])
    op.drop_column("orders", "sales_channel")
