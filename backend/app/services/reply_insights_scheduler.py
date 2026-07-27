"""
Weekly Sunday scan of Instructions-for-AI prompts → distilled reply insights.

Uses Europe/Vilnius local Sunday 09:00. Catch-up: if the laptop was off on Sunday,
the next hourly check runs the scan once the Sunday slot has passed and has not
yet been recorded.
"""
from __future__ import annotations

import logging
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from app.core.database import async_session_maker
from app.services.reply_insights import (
    SYNC_META_LAST_WEEKLY_SCAN,
    run_weekly_prompt_insight_scan,
)

logger = logging.getLogger(__name__)

WEEKLY_SCAN_TZ = "Europe/Vilnius"
WEEKLY_SCAN_SLOT = dt_time(9, 0)  # Sunday 09:00 local
WEEKLY_SCAN_CHECK_HOURS = 1

_scheduler: AsyncIOScheduler | None = None


def _latest_passed_sunday_slot_utc(now_utc: datetime) -> datetime | None:
    """Most recent Sunday 09:00 (local) that is already in the past, as UTC."""
    tz = ZoneInfo(WEEKLY_SCAN_TZ)
    now_local = now_utc.astimezone(tz)
    # Walk back up to 8 days to find the last Sunday slot
    for day_offset in range(0, 8):
        day = (now_local - timedelta(days=day_offset)).date()
        if day.weekday() != 6:  # Monday=0 … Sunday=6
            continue
        slot_local = datetime.combine(day, WEEKLY_SCAN_SLOT, tzinfo=tz)
        if slot_local <= now_local:
            return slot_local.astimezone(timezone.utc)
    return None


async def run_due_weekly_insight_scan() -> None:
    """Run weekly distill if the latest Sunday slot is not yet covered."""
    now_utc = datetime.now(timezone.utc)
    due_utc = _latest_passed_sunday_slot_utc(now_utc)
    if due_utc is None:
        return

    async with async_session_maker() as db:
        from app.services.reply_insights import _get_sync_meta

        raw_last = await _get_sync_meta(db, SYNC_META_LAST_WEEKLY_SCAN)

    last: datetime | None = None
    if raw_last:
        try:
            parsed = datetime.fromisoformat(raw_last.replace("Z", "+00:00"))
            last = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            last = None

    if last is not None and last >= due_utc:
        return

    logger.info(
        "Weekly reply-insight scan due (slot %s; last=%s)",
        due_utc.isoformat(),
        raw_last or "never",
    )
    try:
        async with async_session_maker() as db:
            summary = await run_weekly_prompt_insight_scan(db)
        logger.info("Weekly reply-insight scan OK: %s", summary)
    except Exception:
        logger.exception("Weekly reply-insight scan failed")


def start_reply_insights_scheduler(scheduler: AsyncIOScheduler | None = None) -> AsyncIOScheduler:
    """
    Attach weekly insight catch-up job to an existing scheduler, or create one.
    """
    global _scheduler
    own = scheduler is None
    if scheduler is None:
        if _scheduler is not None:
            return _scheduler
        scheduler = AsyncIOScheduler(timezone=timezone.utc)

    scheduler.add_job(
        run_due_weekly_insight_scan,
        trigger=IntervalTrigger(hours=WEEKLY_SCAN_CHECK_HOURS),
        id="reply_insights_weekly_scan",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=90),
    )
    logger.info(
        "Reply insights weekly scan: Sundays %s %s (catch-up checked every %sh)",
        WEEKLY_SCAN_SLOT.strftime("%H:%M"),
        WEEKLY_SCAN_TZ,
        WEEKLY_SCAN_CHECK_HOURS,
    )

    if own:
        scheduler.start()
        _scheduler = scheduler
    return scheduler


def shutdown_reply_insights_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
