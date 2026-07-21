"""App branding (logo, favicon, display name).

Revision ID: 028_app_branding
Revises: 027_oc_inbound_custom_tracking_number
Create Date: 2026-07-21
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "028_app_branding"
down_revision: Union[str, None] = "027_oc_inbound_custom_tracking_number"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_branding" not in inspector.get_table_names():
        op.create_table(
            "app_branding",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("app_name", sa.String(length=120), nullable=False, server_default="EvampOps"),
            sa.Column("logo_mime", sa.String(length=100), nullable=True),
            sa.Column("logo_data", sa.LargeBinary(), nullable=True),
            sa.Column("favicon_mime", sa.String(length=100), nullable=True),
            sa.Column("favicon_data", sa.LargeBinary(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )
        op.execute(
            sa.text("INSERT INTO app_branding (id, app_name) VALUES (1, 'EvampOps') ON CONFLICT DO NOTHING")
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_branding" in inspector.get_table_names():
        op.drop_table("app_branding")
