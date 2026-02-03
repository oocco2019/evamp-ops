"""Add order and line item pricing, tax, and fees from Fulfillment API

Revision ID: 008_add_order_line_pricing_tax_fees
Revises: 007_add_ai_learning_tables
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "008_add_order_line_pricing_tax_fees"
down_revision: Union[str, None] = "007_add_ai_learning_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Order: pricing and fees from Fulfillment API pricingSummary + totalFeeBasisAmount, totalMarketplaceFee
    op.add_column(
        "orders",
        sa.Column("order_currency", sa.String(3), nullable=True, comment="Order currency (e.g. USD)"),
    )
    op.add_column(
        "orders",
        sa.Column("price_subtotal", sa.Numeric(12, 2), nullable=True, comment="pricingSummary.priceSubtotal"),
    )
    op.add_column(
        "orders",
        sa.Column("price_total", sa.Numeric(12, 2), nullable=True, comment="pricingSummary.total (buyer paid)"),
    )
    op.add_column(
        "orders",
        sa.Column("tax_total", sa.Numeric(12, 2), nullable=True, comment="pricingSummary.tax (remitted)"),
    )
    op.add_column(
        "orders",
        sa.Column("delivery_cost", sa.Numeric(12, 2), nullable=True, comment="pricingSummary.deliveryCost"),
    )
    op.add_column(
        "orders",
        sa.Column("price_discount", sa.Numeric(12, 2), nullable=True, comment="pricingSummary.priceDiscount (negative)"),
    )
    op.add_column(
        "orders",
        sa.Column("fee_total", sa.Numeric(12, 2), nullable=True, comment="pricingSummary.fee (special fees)"),
    )
    op.add_column(
        "orders",
        sa.Column("total_fee_basis_amount", sa.Numeric(12, 2), nullable=True, comment="Base amount for FVF calc"),
    )
    op.add_column(
        "orders",
        sa.Column("total_marketplace_fee", sa.Numeric(12, 2), nullable=True, comment="eBay fees for order"),
    )
    op.add_column(
        "orders",
        sa.Column("order_payment_status", sa.String(50), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("sales_record_reference", sa.String(100), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("ebay_collect_and_remit_tax", sa.Boolean(), nullable=True),
    )

    # LineItem: pricing and tax
    op.add_column(
        "line_items",
        sa.Column("currency", sa.String(3), nullable=True),
    )
    op.add_column(
        "line_items",
        sa.Column("line_item_cost", sa.Numeric(12, 2), nullable=True, comment="Selling price before discounts"),
    )
    op.add_column(
        "line_items",
        sa.Column("discounted_line_item_cost", sa.Numeric(12, 2), nullable=True),
    )
    op.add_column(
        "line_items",
        sa.Column("line_total", sa.Numeric(12, 2), nullable=True, comment="Line total (item + tax etc)"),
    )
    op.add_column(
        "line_items",
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("orders", "ebay_collect_and_remit_tax")
    op.drop_column("orders", "sales_record_reference")
    op.drop_column("orders", "order_payment_status")
    op.drop_column("orders", "total_marketplace_fee")
    op.drop_column("orders", "total_fee_basis_amount")
    op.drop_column("orders", "fee_total")
    op.drop_column("orders", "price_discount")
    op.drop_column("orders", "delivery_cost")
    op.drop_column("orders", "tax_total")
    op.drop_column("orders", "price_total")
    op.drop_column("orders", "price_subtotal")
    op.drop_column("orders", "order_currency")

    op.drop_column("line_items", "tax_amount")
    op.drop_column("line_items", "line_total")
    op.drop_column("line_items", "discounted_line_item_cost")
    op.drop_column("line_items", "line_item_cost")
    op.drop_column("line_items", "currency")
