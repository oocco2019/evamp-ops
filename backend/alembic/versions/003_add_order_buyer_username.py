"""add order buyer_username

Revision ID: 003_add_order_buyer_username
Revises: 002_add_order_cancel_status
Create Date: 2026-01-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "003_add_order_buyer_username"
down_revision: Union[str, None] = "002_add_order_cancel_status"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "buyer_username",
            sa.String(255),
            nullable=True,
            comment="eBay buyer.username (buyer user ID)",
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "buyer_username")
