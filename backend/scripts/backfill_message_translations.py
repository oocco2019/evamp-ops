"""
One-off backfill: detect language and persist de→en translated_content for existing messages.

Uses the same local OPUS-MT path as sync / translate-all. Loops until no candidates remain
(messages with no translated_content and detected_language null or 'de').

Run via Docker:
  docker compose exec backend python scripts/backfill_message_translations.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from sqlalchemy import func, or_, select

_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from app.core.database import async_session_maker
from app.models.messages import Message
from app.services.local_translation import translate_untranslated_batch


async def _pending_count() -> int:
    async with async_session_maker() as db:
        stmt = (
            select(func.count())
            .select_from(Message)
            .where(Message.translated_content.is_(None))
            .where(Message.content.isnot(None))
            .where(Message.content != "(attachment)")
            .where(Message.content != "")
            .where(
                or_(
                    Message.detected_language.is_(None),
                    Message.detected_language == "de",
                )
            )
        )
        return int(await db.scalar(stmt) or 0)


async def run(batch_size: int = 100) -> None:
    total_translated = 0
    batch_num = 0
    while True:
        pending = await _pending_count()
        if pending == 0:
            break
        batch_num += 1
        n = await translate_untranslated_batch(limit=batch_size)
        total_translated += n
        remaining = await _pending_count()
        print(
            f"Batch {batch_num}: translated {n} message(s); "
            f"~{pending} pending before batch; ~{remaining} after; "
            f"total translated {total_translated}"
        )
        if n == 0 and remaining >= pending:
            print(f"Stopping: {remaining} row(s) cannot be translated (empty or attachment-only).")
            break
    print(f"Done. Translated {total_translated} German message(s).")


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
