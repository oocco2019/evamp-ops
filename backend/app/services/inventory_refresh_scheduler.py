"""
Periodic inventory refresh: incremental eBay import + OC SKU/inventory + OC stock movement + inbound cache.
Runs in-process while the API is up; set INVENTORY_REFRESH_INTERVAL_MINUTES=0 to disable.

Each step runs in its own DB session. Failures are logged but do not skip later steps (so inbound
still runs if SKU mapping fails, matching the goal of refreshing all Inventory Status data).
"""
from __future__ import annotations

import logging
from datetime import datetime, time as dt_time, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import HTTPException

from app.api.inventory_status import (
    SYNC_META_INBOUND_LAST_FULL,
    _get_sync_meta_value,
    execute_oc_inbound_sync,
    execute_oc_sku_mappings_sync,
    execute_stock_movement_pull,
)
from app.api.stock import execute_order_import, execute_shopify_order_import
from app.services.shopify_settings import shopify_configured_db
from app.core.config import settings
from app.core.database import async_session_maker

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Daily full inbound-orders sync (catch-up): local clock slots and timezone.
# The backend runs only while the laptop is on, so we cannot rely on firing at the exact minute.
# Instead we check hourly (and at startup) and run a full sync when a slot for today has passed
# and no full sync has happened since that slot. This self-heals when the machine was off.
FULL_INBOUND_SYNC_TZ = "Europe/Vilnius"
FULL_INBOUND_SYNC_SLOTS: tuple[dt_time, ...] = (dt_time(7, 0), dt_time(13, 0))
FULL_INBOUND_CATCHUP_CHECK_HOURS = 1


def _latest_passed_slot_utc(now_utc: datetime) -> datetime | None:
    """Most recent daily slot (FULL_INBOUND_SYNC_SLOTS, local tz) that is already in the past, as UTC."""
    tz = ZoneInfo(FULL_INBOUND_SYNC_TZ)
    now_local = now_utc.astimezone(tz)
    passed: list[datetime] = []
    for day_offset in (0, -1):  # today and yesterday (covers early morning before the first slot)
        day = (now_local + timedelta(days=day_offset)).date()
        for slot in FULL_INBOUND_SYNC_SLOTS:
            slot_local = datetime.combine(day, slot, tzinfo=tz)
            if slot_local <= now_local:
                passed.append(slot_local)
    if not passed:
        return None
    return max(passed).astimezone(timezone.utc)


async def run_due_full_inbound_syncs() -> None:
    """
    Run a FULL inbound sync if the most recent daily slot has not yet been covered by a full sync.
    Idempotent per slot: execute_oc_inbound_sync(full=True) records SYNC_META_INBOUND_LAST_FULL.
    """
    now_utc = datetime.now(timezone.utc)
    last_due_utc = _latest_passed_slot_utc(now_utc)
    if last_due_utc is None:
        return

    async with async_session_maker() as db:
        raw_last_full = await _get_sync_meta_value(db, SYNC_META_INBOUND_LAST_FULL)

    last_full: datetime | None = None
    if raw_last_full:
        try:
            parsed = datetime.fromisoformat(raw_last_full.replace("Z", "+00:00"))
            last_full = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            last_full = None

    if last_full is not None and last_full >= last_due_utc:
        return  # already fully synced after the most recent slot

    logger.info(
        "Full inbound sync due (slot %s; last_full=%s): running full backfill",
        last_due_utc.isoformat(),
        raw_last_full or "never",
    )
    try:
        async with async_session_maker() as db:
            inb = await execute_oc_inbound_sync(db, full=True)
        logger.info("Scheduled FULL OC inbound sync OK: upserted %s row(s)", inb.synced)
    except HTTPException as e:
        logger.warning("Scheduled full inbound sync skipped: %s", e.detail)
    except Exception:
        logger.exception("Scheduled full inbound sync failed")


async def run_scheduled_inventory_refresh() -> None:
    """Same steps as Inventory Status 'Pull latest data' (incremental); steps are independent."""
    logger.info("Scheduled inventory refresh started")

    # 1) eBay orders (incremental)
    try:
        async with async_session_maker() as db:
            r = await execute_order_import(db, "incremental")
        if r.error:
            logger.warning("Scheduled order import finished with error: %s", r.error)
        else:
            logger.info(
                "Scheduled order import OK: +%s orders, +%s lines (updated %s/%s)",
                r.orders_added,
                r.line_items_added,
                r.orders_updated,
                r.line_items_updated,
            )
    except HTTPException as e:
        logger.warning("Scheduled order import skipped: %s", e.detail)
    except Exception:
        logger.exception("Scheduled order import failed")

    try:
        r_sh = None
        async with async_session_maker() as db:
            if await shopify_configured_db(db):
                r_sh = await execute_shopify_order_import(db, "incremental")
        if r_sh is not None:
            if r_sh.error:
                logger.warning("Scheduled Shopify import finished with error: %s", r_sh.error)
            else:
                logger.info(
                    "Scheduled Shopify import OK: +%s orders, +%s lines (updated %s/%s)",
                    r_sh.orders_added,
                    r_sh.line_items_added,
                    r_sh.orders_updated,
                    r_sh.line_items_updated,
                )
    except Exception:
        logger.exception("Scheduled Shopify import failed")

    # 2) OC SKU mappings + inventory snapshot
    try:
        async with async_session_maker() as db:
            sku_res = await execute_oc_sku_mappings_sync(db)
        logger.info(
            "Scheduled OC SKU/inventory sync OK: mappings=%s, inventory_rows=%s",
            sku_res.synced,
            sku_res.inventory_rows,
        )
    except HTTPException as e:
        logger.warning("Scheduled OC SKU/inventory sync skipped: %s", e.detail)
    except Exception:
        logger.exception("Scheduled OC SKU/inventory sync failed")

    # 2b) OC stock movement -> DB (incremental overlap; idempotent upserts)
    try:
        async with async_session_maker() as db:
            mv = await execute_stock_movement_pull(db, incremental=True)
        logger.info(
            "Scheduled OC stock movement sync OK: fetched=%s inserted=%s (%s → %s) clamped=%s",
            mv.fetched,
            mv.inserted,
            mv.from_date,
            mv.to_date,
            mv.clamped,
        )
    except HTTPException as e:
        logger.warning("Scheduled OC stock movement skipped: %s", e.detail)
    except Exception:
        logger.exception("Scheduled OC stock movement failed")

    # 3) Inbound orders cache (incremental)
    try:
        async with async_session_maker() as db:
            inb = await execute_oc_inbound_sync(db, full=False)
        logger.info("Scheduled OC inbound sync OK: upserted %s row(s)", inb.synced)
    except HTTPException as e:
        logger.warning("Scheduled OC inbound sync skipped: %s", e.detail)
    except Exception:
        logger.exception("Scheduled OC inbound sync failed")

    logger.info("Scheduled inventory refresh finished")


def start_inventory_refresh_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    minutes = settings.INVENTORY_REFRESH_INTERVAL_MINUTES
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    if minutes > 0:
        scheduler.add_job(
            run_scheduled_inventory_refresh,
            trigger=IntervalTrigger(minutes=minutes),
            id="inventory_refresh",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            next_run_time=datetime.now(timezone.utc),
        )
        logger.info(
            "Inventory refresh scheduler: every %s minute(s) (eBay + OC SKU/inventory + stock movement + inbound), first run soon",
            minutes,
        )
    else:
        logger.info(
            "Incremental inventory refresh disabled (INVENTORY_REFRESH_INTERVAL_MINUTES=%s); full inbound catch-up still active",
            minutes,
        )

    # Daily full inbound sync (catch-up): hourly check, first check shortly after startup.
    scheduler.add_job(
        run_due_full_inbound_syncs,
        trigger=IntervalTrigger(hours=FULL_INBOUND_CATCHUP_CHECK_HOURS),
        id="inbound_full_catchup",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc) + timedelta(seconds=45),
    )
    logger.info(
        "Daily full inbound sync (catch-up) for slots %s %s, checked every %sh",
        [s.strftime("%H:%M") for s in FULL_INBOUND_SYNC_SLOTS],
        FULL_INBOUND_SYNC_TZ,
        FULL_INBOUND_CATCHUP_CHECK_HOURS,
    )

    scheduler.start()
    _scheduler = scheduler


def shutdown_inventory_refresh_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
