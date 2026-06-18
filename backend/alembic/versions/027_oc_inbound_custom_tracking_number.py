"""Add user override for inbound Tracking # column.

Revision ID: 027_oc_inbound_custom_tracking_number
Revises: 026_oc_inbound_custom_courier_url
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "027_oc_inbound_custom_tracking_number"
down_revision: Union[str, None] = "026_oc_inbound_custom_courier_url"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("oc_inbound_orders")}
    if "custom_tracking_number" not in cols:
        op.add_column(
            "oc_inbound_orders",
            sa.Column("custom_tracking_number", sa.String(length=500), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("oc_inbound_orders")}
    if "custom_tracking_number" in cols:
        op.drop_column("oc_inbound_orders", "custom_tracking_number")
