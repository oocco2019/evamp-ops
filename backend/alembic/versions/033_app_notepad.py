"""Create app_notepad and migrate company_notes off app_branding.

Revision ID: 033_app_notepad
Revises: 032_app_branding_company_notes
Create Date: 2026-07-23
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "033_app_notepad"
down_revision: Union[str, None] = "032_app_branding_company_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

NOTEPAD_ID = 1


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "app_notepad" not in tables:
        op.create_table(
            "app_notepad",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    body = ""
    if "app_branding" in tables:
        branding_cols = {c["name"] for c in sa.inspect(bind).get_columns("app_branding")}
        if "company_notes" in branding_cols:
            row = bind.execute(sa.text("SELECT company_notes FROM app_branding WHERE id = 1")).fetchone()
            if row and row[0]:
                body = row[0]

    bind.execute(
        sa.text(
            """
            INSERT INTO app_notepad (id, body, updated_at)
            VALUES (:id, :body, NOW())
            ON CONFLICT (id) DO UPDATE
            SET body = CASE
                WHEN app_notepad.body = '' AND EXCLUDED.body <> '' THEN EXCLUDED.body
                ELSE app_notepad.body
            END,
            updated_at = CASE
                WHEN app_notepad.body = '' AND EXCLUDED.body <> '' THEN NOW()
                ELSE app_notepad.updated_at
            END
            """
        ),
        {"id": NOTEPAD_ID, "body": body},
    )

    if "app_branding" in tables:
        branding_cols = {c["name"] for c in sa.inspect(bind).get_columns("app_branding")}
        if "company_notes" in branding_cols:
            op.drop_column("app_branding", "company_notes")


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "app_branding" in tables:
        branding_cols = {c["name"] for c in inspector.get_columns("app_branding")}
        if "company_notes" not in branding_cols:
            op.add_column("app_branding", sa.Column("company_notes", sa.Text(), nullable=True))

        if "app_notepad" in tables:
            row = bind.execute(sa.text("SELECT body FROM app_notepad WHERE id = 1")).fetchone()
            if row and row[0]:
                bind.execute(
                    sa.text("UPDATE app_branding SET company_notes = :body WHERE id = 1"),
                    {"body": row[0]},
                )

    if "app_notepad" in sa.inspect(bind).get_table_names():
        op.drop_table("app_notepad")
