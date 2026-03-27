"""
Periodic inventory refresh: incremental eBay import + OC SKU/inventory + inbound cache.
Runs in-process while the API is up; set INVENTORY_REFRESH_INTERVAL_MINUTES=0 to disable.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import HTTPException

from app.api.inventory_status import execute_oc_inbound_sync, execute_oc_sku_mappings_sync
from app.api.stock import execute_order_import
from app.core.config import settings
from app.core.database import async_session_maker

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None


async def run_scheduled_inventory_refresh() -> None:
    """Same pipeline as Inventory Status 'Pull latest data' (incremental)."""
    logger.info("Scheduled inventory refresh started")
    try:
        async with async_session_maker() as db:
            r = await execute_order_import(db, "incremental")
        if r.error:
            logger.warning("Scheduled order import finished with error: %s", r.error)
    except HTTPException as e:
        logger.warning("Scheduled order import skipped: %s", e.detail)
        return
    except Exception:
        logger.exception("Scheduled order import failed")
        return

    try:
        async with async_session_maker() as db:
            await execute_oc_sku_mappings_sync(db)
    except HTTPException as e:
        logger.warning("Scheduled OC SKU/inventory sync skipped: %s", e.detail)
        return
    except Exception:
        logger.exception("Scheduled OC SKU/inventory sync failed")
        return

    try:
        async with async_session_maker() as db:
            await execute_oc_inbound_sync(db, full=False)
    except HTTPException as e:
        logger.warning("Scheduled OC inbound sync skipped: %s", e.detail)
    except Exception:
        logger.exception("Scheduled OC inbound sync failed")

    logger.info("Scheduled inventory refresh finished")


def start_inventory_refresh_scheduler() -> None:
    global _scheduler
    minutes = settings.INVENTORY_REFRESH_INTERVAL_MINUTES
    if minutes <= 0:
        logger.info("Inventory refresh scheduler disabled (INVENTORY_REFRESH_INTERVAL_MINUTES=%s)", minutes)
        return
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        run_scheduled_inventory_refresh,
        trigger=IntervalTrigger(minutes=minutes),
        id="inventory_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Inventory refresh scheduler: every %s minute(s)", minutes)


def shutdown_inventory_refresh_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
