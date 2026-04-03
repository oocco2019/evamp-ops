"""Clear putaway_at/arrived_at estimates for inbounds first seen before today (UTC)

Revision ID: 020_clear_inbound_stage_estimates_before_today
Revises: 019_oc_inbound_arrived_estimates
Create Date: 2026-04-04
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "020_clear_inbound_stage_estimates_before_today"
down_revision: Union[str, None] = "019_oc_inbound_arrived_estimates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "oc_inbound_orders" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("oc_inbound_orders")}
    if "putaway_at" not in cols and "arrived_at" not in cols:
        return
    # Naive UTC timestamps: compare calendar day in UTC to match app logic (datetime.utcnow().date()).
    op.execute(
        sa.text(
            """
            UPDATE oc_inbound_orders
            SET putaway_at = NULL, arrived_at = NULL
            WHERE COALESCE(inbound_at, synced_at)::date < (CURRENT_TIMESTAMP AT TIME ZONE 'UTC')::date
            """
        )
    )


def downgrade() -> None:
    # Cannot restore cleared estimates.
    pass
