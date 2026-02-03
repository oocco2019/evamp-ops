"""Add order ad_fees (NON_SALE_CHARGE from Finances API)

Revision ID: 010_add_order_ad_fees
Revises: 009_add_order_total_due_seller
Create Date: 2026-02-02

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "010_add_order_ad_fees"
down_revision: Union[str, None] = "009_add_order_total_due_seller"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "ad_fees_total",
            sa.Numeric(12, 2),
            nullable=True,
            comment="Sum of NON_SALE_CHARGE (e.g. ad fees) from Finances API",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "ad_fees_currency",
            sa.String(3),
            nullable=True,
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "ad_fees_breakdown",
            sa.JSON(),
            nullable=True,
            comment="List of {fee_type, transaction_memo, amount} from Finances API",
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "ad_fees_breakdown")
    op.drop_column("orders", "ad_fees_currency")
    op.drop_column("orders", "ad_fees_total")
