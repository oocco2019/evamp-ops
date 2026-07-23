"""Add label_compose_templates for Returns A4 layout cache.

Revision ID: 034_label_compose_templates
Revises: 033_app_notepad
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "034_label_compose_templates"
down_revision: Union[str, None] = "033_app_notepad"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "label_compose_templates" in inspector.get_table_names():
        return
    op.create_table(
        "label_compose_templates",
        sa.Column("fingerprint", sa.String(64), primary_key=True),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("arrangement_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "label_compose_templates" in inspector.get_table_names():
        op.drop_table("label_compose_templates")
