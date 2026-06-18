"""Add orders.raw_payload to retain full marketplace order JSON for long-term recovery.

Platforms (eBay, Shopify) purge orders after a limited window; this column keeps the complete
raw order object we received so data is recoverable years later. See docs/DATA_RETENTION.md.

Revision ID: 025_orders_raw_payload
Revises: 024_drop_oc_sku_inventory_history
Create Date: 2026-06-08
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "025_orders_raw_payload"
down_revision: Union[str, None] = "024_drop_oc_sku_inventory_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("orders")}
    if "raw_payload" not in cols:
        op.add_column("orders", sa.Column("raw_payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("orders")}
    if "raw_payload" in cols:
        op.drop_column("orders", "raw_payload")
