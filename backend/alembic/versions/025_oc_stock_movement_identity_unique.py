"""Use full OC stock movement line identity for uniqueness.

Revision ID: 025_oc_stock_movement_identity_unique
Revises: 024_drop_oc_sku_inventory_history
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "025_oc_stock_movement_identity_unique"
down_revision: Union[str, None] = "024_drop_oc_sku_inventory_history"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OLD_CONSTRAINT = "uq_oc_stock_mov_conn_movement"
NEW_CONSTRAINT = "uq_oc_stock_mov_conn_movement_identity"
TABLE = "oc_stock_movement_line"
IDENTITY_COLUMNS = [
    "connection_id",
    "movement_id",
    "mfskuid",
    "service_region",
    "update_time_raw",
]


def _constraint_names() -> set[str] | None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if TABLE not in inspector.get_table_names():
        return None
    return {c["name"] for c in inspector.get_unique_constraints(TABLE)}


def upgrade() -> None:
    names = _constraint_names()
    if names is None:
        return
    if OLD_CONSTRAINT in names:
        op.drop_constraint(OLD_CONSTRAINT, TABLE, type_="unique")
    if NEW_CONSTRAINT not in names:
        op.create_unique_constraint(NEW_CONSTRAINT, TABLE, IDENTITY_COLUMNS)


def downgrade() -> None:
    names = _constraint_names()
    if names is None:
        return
    if NEW_CONSTRAINT in names:
        op.drop_constraint(NEW_CONSTRAINT, TABLE, type_="unique")
    if OLD_CONSTRAINT not in names:
        op.create_unique_constraint(OLD_CONSTRAINT, TABLE, ["connection_id", "movement_id"])
