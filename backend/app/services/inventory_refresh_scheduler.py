"""
Periodic inventory refresh: incremental eBay import + OC SKU/inventory + OC stock movement + inbound cache.
Runs in-process while the API is up; set INVENTORY_REFRESH_INTERVAL_MINUTES=0 to disable.

Each step runs in its own DB session. Failures are logged but do not skip later steps (so inbound
still runs if SKU mapping fails, matching the goal of refreshing all Inventory Status data).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import HTTPException

from app.api.inventory_status import (
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
    minutes = settings.INVENTORY_REFRESH_INTERVAL_MINUTES
    if minutes <= 0:
        logger.info("Inventory refresh scheduler disabled (INVENTORY_REFRESH_INTERVAL_MINUTES=%s)", minutes)
        return
    if _scheduler is not None:
        return
    _scheduler = AsyncIOScheduler(timezone=timezone.utc)
    _scheduler.add_job(
        run_scheduled_inventory_refresh,
        trigger=IntervalTrigger(minutes=minutes),
        id="inventory_refresh",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),
    )
    _scheduler.start()
    logger.info(
        "Inventory refresh scheduler: every %s minute(s) (eBay + OC SKU/inventory + stock movement + inbound), first run soon",
        minutes,
    )


def shutdown_inventory_refresh_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
