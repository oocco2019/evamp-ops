"""Drop CS router tables (Messages-Test removed).

Revision ID: 042_drop_cs_router_tables
Revises: 041_premade_messages
Create Date: 2026-09-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "042_drop_cs_router_tables"
down_revision: Union[str, None] = "041_premade_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "reply_stage_templates" in tables:
        op.drop_table("reply_stage_templates")
    if "known_issues" in tables:
        op.drop_table("known_issues")


def downgrade() -> None:
    # Intentionally minimal: Messages-Test / CS router is removed; recreate empty shells only.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "known_issues" not in tables:
        op.create_table(
            "known_issues",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("issue_id", sa.String(80), nullable=False, unique=True),
            sa.Column("symptom_keywords", sa.JSON(), nullable=False),
            sa.Column("applies_to_sku", sa.String(500), nullable=False, server_default="*"),
            sa.Column("diagnosis", sa.Text(), nullable=False),
            sa.Column("confidence", sa.String(20), nullable=False, server_default="medium"),
            sa.Column("skip_to_action", sa.String(40), nullable=False, server_default="none"),
            sa.Column("evidence_required", sa.String(20), nullable=False, server_default="none"),
            sa.Column("disposal_note", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("batch_safe", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("requires_image", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
    if "reply_stage_templates" not in tables:
        op.create_table(
            "reply_stage_templates",
            sa.Column("stage_key", sa.String(60), primary_key=True),
            sa.Column("instruction", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )
