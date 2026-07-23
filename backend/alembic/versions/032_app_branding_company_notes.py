"""Add company_notes to app_branding for home-page company details.

Revision ID: 032_app_branding_company_notes
Revises: 031_playbook_sku_scope_len
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "032_app_branding_company_notes"
down_revision: Union[str, None] = "031_playbook_sku_scope_len"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_branding" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("app_branding")}
    if "company_notes" not in cols:
        op.add_column("app_branding", sa.Column("company_notes", sa.Text(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "app_branding" not in inspector.get_table_names():
        return
    cols = {c["name"] for c in inspector.get_columns("app_branding")}
    if "company_notes" in cols:
        op.drop_column("app_branding", "company_notes")
