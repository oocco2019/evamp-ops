"""Add email_templates table

Revision ID: 006_add_email_templates
Revises: 005_move_flag_to_thread
Create Date: 2026-02-02

"""
from alembic import op
import sqlalchemy as sa

revision = "006_add_email_templates"
down_revision = "005_move_flag_to_thread"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "email_templates",
        sa.Column("id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("recipient_email", sa.String(255), nullable=False),
        sa.Column("subject", sa.String(500), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("email_templates")
