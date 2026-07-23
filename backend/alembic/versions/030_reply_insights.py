"""Reply insights table for pending policy/playbook candidates.

Revision ID: 030_reply_insights
Revises: 029_reply_policy_playbook
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "030_reply_insights"
down_revision: Union[str, None] = "029_reply_policy_playbook"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reply_insights" not in inspector.get_table_names():
        op.create_table(
            "reply_insights",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
            sa.Column("kind", sa.String(length=20), nullable=False),
            sa.Column("fingerprint", sa.String(length=64), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("symptom", sa.Text(), nullable=True),
            sa.Column("sku_scope", sa.String(length=100), nullable=False, server_default="*"),
            sa.Column("source", sa.String(length=40), nullable=False, server_default="extra_instructions"),
            sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("evidence", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        )
        op.create_index("ix_reply_insights_fingerprint", "reply_insights", ["fingerprint"])
        op.create_index("ix_reply_insights_status", "reply_insights", ["status"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "reply_insights" in inspector.get_table_names():
        op.drop_index("ix_reply_insights_status", table_name="reply_insights")
        op.drop_index("ix_reply_insights_fingerprint", table_name="reply_insights")
        op.drop_table("reply_insights")
