"""add order cancel_status

Revision ID: 002_add_order_cancel_status
Revises: 001_initial
Create Date: 2026-01-30

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_add_order_cancel_status"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "cancel_status",
            sa.String(20),
            nullable=True,
            comment="eBay cancelStatus.cancelState: CANCELED, IN_PROGRESS, NONE_REQUESTED",
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "cancel_status")
