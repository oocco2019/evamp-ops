"""
Add safety and reassurance stage templates for CS router (Messages-Test).
"""

from typing import Optional, Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "036_cs_router_safety_stages"
down_revision: Union[str, None] = "035_cs_router_known_issues"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SAFETY_STAGES = [
    (
        "safety",
        "A burned, melted, or overheated plug or socket is the most serious fault. It may be a fire risk in the buyer's home.\n\n"
        "Lead with a sincere human reaction BEFORE any logistics.\n"
        "Say you are glad they are safe and acknowledge how alarming this is.\n"
        "Only after that, resolve the case: confirm the replacement or refund approach, then give one clear next step.\n"
        "Include the disposal note if applicable, and provide cause guidance (keep the socket dry, remove debris, and avoid unsuitable outlets).\n"
        "Do not start with a tracking number.",
    ),
    (
        "reassurance",
        "The buyer has a protective error such as leakage, RCD trip, earth fault, or a tripped breaker.\n\n"
        "This is the device working correctly to protect them. It is NOT dangerous.\n"
        "Reassure them calmly in the first line.\n"
        "Then give one short troubleshooting step (dry socket, remove debris, and try a different wall outlet if needed).",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "reply_stage_templates" not in tables:
        # Should not happen because 035 created it, but keep the migration idempotent.
        op.create_table(
            "reply_stage_templates",
            sa.Column("stage_key", sa.String(60), primary_key=True),
            sa.Column("instruction", sa.Text(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    existing = {
        r[0] for r in bind.execute(sa.text("SELECT stage_key FROM reply_stage_templates")).fetchall()
    }
    for stage_key, instruction in SAFETY_STAGES:
        if stage_key in existing:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO reply_stage_templates (stage_key, instruction, updated_at) "
                "VALUES (:k, :i, now())"
            ),
            {"k": stage_key, "i": instruction},
        )


def downgrade() -> None:
    # Keep downgrade simple. In production, templates are safe to keep as they are not destructive.
    pass

