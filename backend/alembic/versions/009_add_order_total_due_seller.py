"""Add order totalDueSeller (order earnings / payout to seller)

Revision ID: 009_add_order_total_due_seller
Revises: 008_add_order_line_pricing_tax_fees
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "009_add_order_total_due_seller"
down_revision: Union[str, None] = "008_add_order_line_pricing_tax_fees"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "total_due_seller",
            sa.Numeric(12, 2),
            nullable=True,
            comment="paymentSummary.totalDueSeller (order earnings / payout to seller)",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "total_due_seller_currency",
            sa.String(3),
            nullable=True,
            comment="Currency of total_due_seller (often GBP for UK sellers)",
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "total_due_seller_currency")
    op.drop_column("orders", "total_due_seller")
