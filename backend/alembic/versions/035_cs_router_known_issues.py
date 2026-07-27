"""Known issues register + stage templates for CS router (Messages-Test).

Revision ID: 035_cs_router_known_issues
Revises: 034_label_compose_templates
Create Date: 2026-07-27
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "035_cs_router_known_issues"
down_revision: Union[str, None] = "034_label_compose_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

STAGE_SEEDS = [
    (
        "clarify_or_troubleshoot",
        "Acknowledge the issue in one sentence. Ask ONE clarifying question OR offer ONE "
        "troubleshooting step — not both, not a list. Do not mention video, replacement, or refund yet. "
        "Keep under ~600 characters.",
    ),
    (
        "request_video",
        "Troubleshooting has failed or is exhausted. Ask for a short video (WhatsApp {whatsapp}) "
        "showing the fault with the evamp logo visible. One short paragraph. Do not offer refund or "
        "replacement yet.",
    ),
    (
        "request_photo",
        "Ask for a clear photo of the fault (and the plug/socket if relevant). Keep it short. "
        "Do not offer refund or replacement yet unless the seller's additional instructions say so.",
    ),
    (
        "resolve_replace",
        "Confirm a replacement is being sent. If a disposal note applies, tell them to dispose of "
        "the faulty unit and not return it. Ask for delivery name/address only if not already in the "
        "thread. One short message.",
    ),
    (
        "resolve_refund",
        "Confirm the refund. If the order looks older than ~90 days, note it may go via PayPal and "
        "ask for the PayPal email as a screenshot if needed. One short message.",
    ),
    (
        "arrange_return",
        "Organise the return yourself (free-returns market). Confirm you will send the label. "
        "Warm and brief. Do NOT ask the buyer to arrange or pay postage.",
    ),
    (
        "courier_chase",
        "Acknowledge the delay. Say you've raised it with the courier and warehouse. Give a next "
        "update timing. Offer replacement or refund only if the thread already shows the parcel is lost.",
    ),
    (
        "fitment",
        "Confirm compatibility in one line if clear from the thread, and thank them for checking. "
        "If the vehicle/reg/model isn't clear, say you'll confirm rather than guessing.",
    ),
    (
        "invoice",
        "Confirm the invoice has been (or will be) sent. One or two short sentences only.",
    ),
    (
        "wifi_guide",
        "Give a short, friendly Wi‑Fi/app pairing tip or link to the usual fix. One short message. "
        "Do not dump a full manual.",
    ),
    (
        "cancel",
        "Acknowledge the cancel/change request. State what you can do next (cancel if not shipped, "
        "or refuse delivery / return path if already shipped). One short message.",
    ),
    (
        "follow_up",
        "Write a brief polite nudge asking if they still need help or have an update. No wall of text. "
        "Do not restart the whole support arc.",
    ),
    (
        "clarify",
        "Acknowledge briefly and ask ONE clarifying question about what they need. Do not offer "
        "refund, replacement, or video yet.",
    ),
]


def upgrade() -> None:
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

    # Seeds (idempotent)
    conn = op.get_bind()
    existing = {
        r[0]
        for r in conn.execute(sa.text("SELECT issue_id FROM known_issues")).fetchall()
    }
    seeds = [
        (
            "white_glue_cover",
            [
                "front off",
                "cover off",
                "glass off",
                "panel off",
                "panel fell",
                "panel lifted",
                "exposed board",
                "front fell",
                "cover fell",
                "glass fell",
            ],
            "*",
            "Front/cover/glass detached (known adhesive issue).",
            "high",
            "resolve_replace",
            "photo",
            True,
            False,
            False,
        ),
        (
            "melted_plug",
            [
                "melted",
                "burnt plug",
                "burned plug",
                "overheated",
                "scorch",
                "melted socket",
                "burnt socket",
            ],
            "*",
            "Possible melted/overheated plug or socket — safety review.",
            "medium",
            "request_photo",
            "photo",
            False,
            False,
            False,
        ),
        (
            "pp_resistor_nocharge",
            [
                "won't charge",
                "wont charge",
                "doesn't charge",
                "does not charge",
                "not charging",
                "oem works",
                "original works",
                "works with original",
            ],
            "*",
            "No-charge fault; often needs video after basic checks.",
            "medium",
            "request_video",
            "video",
            True,
            False,
            False,
        ),
        (
            "wifi_timeout",
            [
                "app timeout",
                "can't pair",
                "cannot pair",
                "won't pair",
                "wlan",
                "wifi timeout",
                "wi-fi timeout",
                "pairing failed",
            ],
            "*",
            "App/Wi‑Fi pairing timeout — send short guide, not full fault arc.",
            "high",
            "none",
            "none",
            False,
            False,
            False,
        ),
    ]
    import json
    from datetime import datetime

    now = datetime.utcnow()
    for row in seeds:
        if row[0] in existing:
            continue
        conn.execute(
            sa.text(
                """
                INSERT INTO known_issues (
                  issue_id, symptom_keywords, applies_to_sku, diagnosis, confidence,
                  skip_to_action, evidence_required, disposal_note, batch_safe, requires_image,
                  active, created_at, updated_at
                ) VALUES (
                  :issue_id, CAST(:keywords AS json), :sku, :diagnosis, :confidence,
                  :skip, :evidence, :disposal, :batch_safe, :req_img,
                  true, :now, :now
                )
                """
            ),
            {
                "issue_id": row[0],
                "keywords": json.dumps(row[1]),
                "sku": row[2],
                "diagnosis": row[3],
                "confidence": row[4],
                "skip": row[5],
                "evidence": row[6],
                "disposal": row[7],
                "batch_safe": row[8],
                "req_img": row[9],
                "now": now,
            },
        )

    existing_stages = {
        r[0]
        for r in conn.execute(sa.text("SELECT stage_key FROM reply_stage_templates")).fetchall()
    }
    for key, instruction in STAGE_SEEDS:
        if key in existing_stages:
            continue
        conn.execute(
            sa.text(
                "INSERT INTO reply_stage_templates (stage_key, instruction, updated_at) "
                "VALUES (:k, :i, :now)"
            ),
            {"k": key, "i": instruction, "now": now},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = inspector.get_table_names()
    if "reply_stage_templates" in tables:
        op.drop_table("reply_stage_templates")
    if "known_issues" in tables:
        op.drop_table("known_issues")
