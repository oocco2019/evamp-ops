"""Customer vehicle details: parsed vehicle make/model/year per order.

This supports the "Settings → Customer Vehicle Details" dashboards.
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "038_customer_vehicle_details"
down_revision: Union[str, None] = "037_stage_safety_tone_socket_lang"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "customer_vehicle_details" not in tables:
        op.create_table(
            "customer_vehicle_details",
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("orders.order_id"), primary_key=True),
            sa.Column("sales_channel", sa.String(20), nullable=False, server_default="ebay"),
            sa.Column("ebay_order_id", sa.String(100), nullable=True),
            sa.Column("order_date", sa.Date(), nullable=False),
            sa.Column("vehicle_make", sa.String(80), nullable=True),
            sa.Column("vehicle_model", sa.String(120), nullable=True),
            sa.Column("vehicle_year", sa.Integer(), nullable=True),
            sa.Column("vehicle_type", sa.String(30), nullable=True),
            sa.Column("vehicle_raw", sa.Text(), nullable=True),
            sa.Column("vehicle_source", sa.String(40), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

        op.create_index(
            "ix_customer_vehicle_details_order_date",
            "customer_vehicle_details",
            ["order_date"],
        )
        op.create_index(
            "ix_customer_vehicle_details_make_model",
            "customer_vehicle_details",
            ["vehicle_make", "vehicle_model"],
        )
        op.create_index(
            "ix_customer_vehicle_details_vehicle_year",
            "customer_vehicle_details",
            ["vehicle_year"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "customer_vehicle_details" in tables:
        op.drop_table("customer_vehicle_details")

