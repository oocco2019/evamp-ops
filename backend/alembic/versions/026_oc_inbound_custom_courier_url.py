"""Add user override for inbound Courier column (custom tracking URL).

Revision ID: 026_oc_inbound_custom_courier_url
Revises: 025_orders_raw_payload
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "026_oc_inbound_custom_courier_url"
down_revision: Union[str, None] = "025_orders_raw_payload"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("oc_inbound_orders")}
    if "custom_courier_url" not in cols:
        op.add_column(
            "oc_inbound_orders",
            sa.Column("custom_courier_url", sa.String(length=2000), nullable=True),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("oc_inbound_orders")}
    if "custom_courier_url" in cols:
        op.drop_column("oc_inbound_orders", "custom_courier_url")
