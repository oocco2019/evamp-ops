"""Widen reply_playbook_entries.sku_scope for comma-separated SKU lists.

Revision ID: 031_playbook_sku_scope_len
Revises: 030_reply_insights
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "031_playbook_sku_scope_len"
down_revision: Union[str, None] = "030_reply_insights"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "reply_playbook_entries",
        "sku_scope",
        existing_type=sa.String(length=100),
        type_=sa.String(length=500),
        existing_nullable=False,
        existing_server_default="*",
    )


def downgrade() -> None:
    op.alter_column(
        "reply_playbook_entries",
        "sku_scope",
        existing_type=sa.String(length=500),
        type_=sa.String(length=100),
        existing_nullable=False,
        existing_server_default="*",
    )
