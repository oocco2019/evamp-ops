"""Reply policies, playbook, AI compositions; clear legacy AI instructions.

Revision ID: 029_reply_policy_playbook
Revises: 028_app_branding
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "029_reply_policy_playbook"
down_revision: Union[str, None] = "028_app_branding"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "reply_policies" not in tables:
        op.create_table(
            "reply_policies",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )

    if "reply_playbook_entries" not in tables:
        op.create_table(
            "reply_playbook_entries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("symptom", sa.Text(), nullable=False, server_default=""),
            sa.Column("resolution", sa.Text(), nullable=False),
            sa.Column("sku_scope", sa.String(length=100), nullable=False, server_default="*"),
            sa.Column("trigger_keywords", sa.JSON(), nullable=True),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )

    if "ai_compositions" not in tables:
        op.create_table(
            "ai_compositions",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("thread_id", sa.String(length=100), nullable=False),
            sa.Column("sku", sa.String(length=100), nullable=True),
            sa.Column("order_id", sa.String(length=100), nullable=True),
            sa.Column("prompt_snapshot", sa.JSON(), nullable=True),
            sa.Column("policy_ids", sa.JSON(), nullable=True),
            sa.Column("playbook_ids", sa.JSON(), nullable=True),
            sa.Column("model_output", sa.Text(), nullable=False),
            sa.Column("adherence_json", sa.JSON(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("now()")),
        )
        op.create_index("ix_ai_compositions_thread_id", "ai_compositions", ["thread_id"])

    if "draft_feedback" in tables:
        cols = {c["name"] for c in inspector.get_columns("draft_feedback")}
        if "composition_id" not in cols:
            op.add_column(
                "draft_feedback",
                sa.Column("composition_id", sa.Integer(), nullable=True),
            )
            op.create_foreign_key(
                "fk_draft_feedback_composition_id",
                "draft_feedback",
                "ai_compositions",
                ["composition_id"],
                ["id"],
                ondelete="SET NULL",
            )

    # Clear legacy instruction blobs (global/SKU free-text).
    if "ai_instructions" in tables:
        op.execute(sa.text("DELETE FROM ai_instructions"))

    # Seed starters only when empty (idempotent re-run safe).
    conn = op.get_bind()
    pol_count = conn.execute(sa.text("SELECT COUNT(*) FROM reply_policies")).scalar()
    if not pol_count:
        conn.execute(
            sa.text(
                """
                INSERT INTO reply_policies (body, enabled, sort_order, created_at, updated_at)
                VALUES (:body, true, :ord, now(), now())
                """
            ),
            {
                "body": (
                    "When drafting responses do not use a comma before and or before a dash "
                    "in ways people do not usually use when messaging."
                ),
                "ord": 0,
            },
        )
        conn.execute(
            sa.text(
                """
                INSERT INTO reply_policies (body, enabled, sort_order, created_at, updated_at)
                VALUES (:body, true, :ord, now(), now())
                """
            ),
            {
                "body": "Maintain a friendly, conversational, and helpful tone.",
                "ord": 1,
            },
        )

    pb_count = conn.execute(sa.text("SELECT COUNT(*) FROM reply_playbook_entries")).scalar()
    if not pb_count:
        conn.execute(
            sa.text(
                """
                INSERT INTO reply_playbook_entries
                  (symptom, resolution, sku_scope, trigger_keywords, enabled, created_at, updated_at)
                VALUES
                  (:symptom, :resolution, '*', NULL, true, now(), now())
                """
            ),
            {
                "symptom": "Shipping labels / return labels",
                "resolution": "Suggest to print the labels on A4 paper.",
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "draft_feedback" in tables:
        cols = {c["name"] for c in inspector.get_columns("draft_feedback")}
        if "composition_id" in cols:
            op.drop_constraint("fk_draft_feedback_composition_id", "draft_feedback", type_="foreignkey")
            op.drop_column("draft_feedback", "composition_id")

    if "ai_compositions" in tables:
        op.drop_index("ix_ai_compositions_thread_id", table_name="ai_compositions")
        op.drop_table("ai_compositions")
    if "reply_playbook_entries" in tables:
        op.drop_table("reply_playbook_entries")
    if "reply_policies" in tables:
        op.drop_table("reply_policies")
