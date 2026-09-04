"""Add listing_video_jobs / _items / _logs tables for persistent add-video jobs.

Revision ID: 039_listing_video_jobs
Revises: 038_customer_vehicle_details
Create Date: 2026-09-03
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "039_listing_video_jobs"
down_revision: Union[str, None] = "038_customer_vehicle_details"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()

    if "listing_video_jobs" not in tables:
        op.create_table(
            "listing_video_jobs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("job_id", sa.String(40), nullable=False, unique=True),
            sa.Column("mode", sa.String(20), nullable=False),
            sa.Column("sku", sa.String(100), nullable=True),
            sa.Column("video_id", sa.String(100), nullable=False),
            sa.Column("marketplace_id", sa.String(20), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("updated_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("error_message", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_listing_video_jobs_job_id", "listing_video_jobs", ["job_id"], unique=True)

    if "listing_video_job_items" not in tables:
        op.create_table(
            "listing_video_job_items",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "job_id", sa.String(40),
                sa.ForeignKey("listing_video_jobs.job_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("item_id", sa.String(32), nullable=False),
            sa.Column("marketplace_id", sa.String(20), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_lvji_job_id", "listing_video_job_items", ["job_id"])
        op.create_index("ix_lvji_job_status", "listing_video_job_items", ["job_id", "status"])

    if "listing_video_job_logs" not in tables:
        op.create_table(
            "listing_video_job_logs",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column(
                "job_id", sa.String(40),
                sa.ForeignKey("listing_video_jobs.job_id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("message", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
        )
        op.create_index("ix_lvjl_job_id", "listing_video_job_logs", ["job_id"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    for t in ("listing_video_job_logs", "listing_video_job_items", "listing_video_jobs"):
        if t in tables:
            op.drop_table(t)
