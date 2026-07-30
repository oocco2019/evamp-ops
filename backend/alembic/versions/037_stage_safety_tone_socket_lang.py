"""Update safety + reassurance stage templates: tone fix and heavy-duty socket language.

Revision ID: 037_stage_safety_tone_socket_lang
Revises: 036_cs_router_safety_stages
Create Date: 2026-07-29
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "037_stage_safety_tone_socket_lang"
down_revision: Union[str, None] = "036_cs_router_safety_stages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SAFETY = """\
The buyer is reporting a burned, melted, or overheated plug or socket.

Open by acknowledging what happened at a human-stranger level — not like a worried family member, \
but like someone who genuinely recognises that this was a stressful thing to deal with. \
A line like "I can imagine that was pretty stressful to deal with" is the right register. \
Do not write "I am so worried" or "I am so glad you are safe" or "we take safety very seriously" \
— that sounds fake from a stranger. Keep it one short sentence, then move on.

After that: resolve the case. Confirm the replacement or refund, the disposal note if applicable, \
and one clear next step.

If cause guidance is relevant (plug or socket issue), say: use a heavy-duty outdoor-rated \
socket designed for EV charging, keep it dry and free of debris, and avoid standard household \
extension leads or inadequate sockets.

Do not start with a tracking number.\
"""

REASSURANCE = """\
The buyer has a protective error such as a leakage warning, RCD trip, earth fault, or tripped breaker.

This is the charger's built-in protection working correctly. It is not a fault and not dangerous.

Open by calmly reassuring them of that in one sentence. Do not apologise as if something went \
wrong, and do not echo their alarm.

Then give one short fix: check the socket is dry and free of debris, and try a different \
heavy-duty outdoor-rated socket designed for EV charging rather than a standard household outlet.\
"""


def upgrade() -> None:
    bind = op.get_bind()
    for stage_key, instruction in [("safety", SAFETY), ("reassurance", REASSURANCE)]:
        bind.execute(
            sa.text(
                "UPDATE reply_stage_templates SET instruction = :i, updated_at = now() "
                "WHERE stage_key = :k"
            ),
            {"k": stage_key, "i": instruction},
        )


def downgrade() -> None:
    pass
