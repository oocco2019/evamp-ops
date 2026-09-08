"""
Get video ID from an eBay listing by item number or listing URL.
Uses Trading API GetItem(ItemID) then Inventory API getInventoryItem(sku) for videoIds.

Also implements a persistent job system for add-video operations so they survive
laptop sleep / browser disconnect: start job → returns job_id → backend keeps running →
frontend polls GET /jobs/{job_id} to read status and logs.
"""
import asyncio
import json
import re
import secrets
import logging
from datetime import datetime, timezone
from typing import List, AsyncIterator, Optional

import httpx
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, async_session_maker
from app.core.config import settings
from app.services.ebay_auth import get_ebay_access_token
from app.services.ebay_client import (
    trading_get_item,
    trading_revise_fixed_price_item,
    trading_remove_video_from_item,
    trading_get_seller_list_by_sku,
    get_inventory_item,
    get_inventory_items,
    get_offers,
    create_or_replace_inventory_item,
)
from app.models.listing_video import ListingVideoJob, ListingVideoJobItem, ListingVideoJobLog

logger = logging.getLogger(__name__)

router = APIRouter()


def _extract_item_id(input_str: str) -> str | None:
    """Extract item ID from '136528644539' or 'https://www.ebay.co.uk/itm/136528644539'. Returns None if not found."""
    s = (input_str or "").strip()
    if not s:
        return None
    m = re.search(r"/itm/(\d{9,14})(?:\?|$|/)", s)
    if m:
        return m.group(1)
    if s.isdigit() and 9 <= len(s) <= 14:
        return s
    return None


class VideoIdResponse(BaseModel):
    """Video IDs are returned exactly as from eBay; use the full string (exact character count) when adding to other listings."""

    item_number: str
    video_ids: List[str] = Field(default_factory=list, description="eBay video IDs; must be used with exact character count in API calls.")
    title: str | None = None
    sku: str | None = None


class AddVideoToSkuRequest(BaseModel):
    video_id: str
    sku: str
    marketplace_id: str | None = None  # e.g. EBAY_US, EBAY_GB; site for GetSellerList and ReviseFixedPriceItem


class AddVideoToSkuResponse(BaseModel):
    sku: str
    video_ids: List[str] = Field(default_factory=list)


def _parse_item_ids(text: str) -> List[str]:
    """Parse item IDs from text: one per line or comma-separated; supports digits or listing URLs."""
    if not text or not text.strip():
        return []
    seen: set[str] = set()
    out: List[str] = []
    for part in re.split(r"[\n,]+", text):
        s = (part or "").strip()
        if not s:
            continue
        item_id = _extract_item_id(s)
        if item_id is None and s.isdigit() and 9 <= len(s) <= 14:
            item_id = s
        if item_id and item_id not in seen:
            seen.add(item_id)
            out.append(item_id)
    return out


class AddVideoToListingsRequest(BaseModel):
    video_id: str
    item_ids: List[str] = Field(default_factory=list, description="Item IDs (listing numbers) or listing URLs.")


def _stream_line(obj: dict) -> bytes:
    return (json.dumps(obj) + "\n").encode("utf-8")


async def _add_video_to_sku_stream(
    video_id: str,
    sku: str,
    access_token: str,
    marketplace_id: str | None = None,
) -> AsyncIterator[bytes]:
    """
    Add video to all listings for this SKU via Trading API (for CSV inventory).
    GetSellerList(sku) → item IDs → ReviseFixedPriceItem each with video_id.
    marketplace_id sets the site (e.g. EBAY_US, EBAY_GB).
    """
    video_id = (video_id or "").strip()
    sku = (sku or "").strip()
    if not video_id or not sku:
        yield _stream_line({"type": "error", "detail": "video_id and sku are required."})
        return

    mkt_label = (marketplace_id or "default").strip() or "default"
    yield _stream_line({"type": "progress", "message": f"Scanning all active listings for SKU {sku} on {mkt_label}… (this may take a few seconds)"})
    item_ids: List[str] = []
    try:
        async for payload in trading_get_seller_list_by_sku(access_token, sku, marketplace_id):
            if isinstance(payload, dict):
                yield _stream_line(payload)
            else:
                item_ids = payload
    except Exception as e:
        logger.warning("listing_video: trading_get_seller_list_by_sku failed: %s", e)
        detail = str(e).strip() or f"{type(e).__name__} while scanning listings for SKU '{sku}'"
        yield _stream_line({"type": "error", "detail": f"Could not get listings for SKU '{sku}': {detail}"})
        return

    if not item_ids:
        yield _stream_line(
            {
                "type": "error",
                "detail": (
                    f"No listings found for SKU '{sku}'. "
                    "Check the SKU matches Custom Label on your active listings for this site."
                ),
            }
        )
        return

    total = len(item_ids)
    yield _stream_line({"type": "listing_count", "count": total})
    yield _stream_line({"type": "progress", "message": f"Found {total} listing(s). Adding video…"})

    updated = 0
    pending = list(item_ids)   # items still to succeed
    attempt = 0
    max_attempts = 4  # 1 initial + 3 retries
    last_errors: dict[str, str] = {}

    while pending and attempt < max_attempts:
        attempt += 1
        if attempt > 1:
            delay = 2 ** (attempt - 1)  # 2s, 4s, 8s
            yield _stream_line({"type": "progress", "message": f"Retrying {len(pending)} failed listing(s) (attempt {attempt}/{max_attempts}, waiting {delay}s)…"})
            import asyncio as _asyncio
            await _asyncio.sleep(delay)

        still_failing: List[str] = []
        offset = total - len(pending)
        for i, item_id in enumerate(pending):
            yield _stream_line({"type": "progress", "message": f"Revising listing {offset + i + 1}/{total} (item {item_id})…"})
            try:
                await trading_revise_fixed_price_item(access_token, item_id, video_id, marketplace_id)
                updated += 1
                last_errors.pop(item_id, None)
            except Exception as e:
                err_msg = str(e).strip() or type(e).__name__
                logger.warning("listing_video: revise item_id=%s attempt=%s failed: %s", item_id, attempt, e)
                still_failing.append(item_id)
                last_errors[item_id] = err_msg
                yield _stream_line({"type": "progress", "message": f"Failed: {item_id} — {err_msg}"})

        # An all-fail round is not a stop condition. Concurrent Revise calls
        # often all 429/timeout together; the delays below exist for that case.
        pending = still_failing

    failed = list(last_errors.keys())
    yield _stream_line({"type": "done", "sku": sku, "updated": updated, "failed": failed, "total": total, "fail_reasons": last_errors})


@router.post("/add-video-to-sku")
async def add_video_to_sku(
    body: AddVideoToSkuRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Add a video ID to the inventory item for the given SKU. Streams NDJSON progress events (realtime).
    Events: progress (message), listing_count (count), done (sku, video_ids), error (detail).
    """
    video_id = (body.video_id or "").strip()
    sku = (body.sku or "").strip()
    marketplace_id = (body.marketplace_id or "").strip() or None
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id is required.")
    if not sku:
        raise HTTPException(status_code=400, detail="sku is required.")

    try:
        access_token = await get_ebay_access_token(db)
    except Exception as e:
        logger.exception("listing_video: get_ebay_access_token failed")
        raise HTTPException(status_code=503, detail=f"eBay auth failed: {e!s}")

    return StreamingResponse(
        _add_video_to_sku_stream(video_id, sku, access_token, marketplace_id),
        media_type="application/x-ndjson",
    )


async def _add_video_to_listings_stream(
    video_id: str,
    item_ids: List[str],
    access_token: str,
) -> AsyncIterator[bytes]:
    """Yield NDJSON progress events; final event is 'done' (updated, failed) or 'error'."""
    video_id = (video_id or "").strip()
    if not video_id:
        yield _stream_line({"type": "error", "detail": "video_id is required."})
        return
    if not item_ids:
        yield _stream_line({"type": "error", "detail": "At least one item ID is required."})
        return

    resolved = []
    for x in item_ids:
        s = (x or "").strip()
        if not s:
            continue
        iid = _extract_item_id(s) if ("/" in s or not s.isdigit()) else (s if 9 <= len(s) <= 14 else None)
        if not iid and s.isdigit() and 9 <= len(s) <= 14:
            iid = s
        if iid:
            resolved.append(iid)
    if not resolved:
        yield _stream_line({"type": "error", "detail": "No valid item IDs (use 9–14 digit listing numbers or listing URLs)."})
        return

    total = len(resolved)
    updated = 0
    failed: List[str] = []

    for i, item_id in enumerate(resolved):
        yield _stream_line({"type": "progress", "message": f"Revising listing {i + 1}/{total} (item {item_id})…"})
        try:
            await trading_revise_fixed_price_item(access_token, item_id, video_id)
            updated += 1
        except Exception as e:
            logger.warning("listing_video: revise item_id=%s failed: %s", item_id, e)
            failed.append(item_id)
            yield _stream_line({"type": "progress", "message": f"Failed: {item_id} — {e!s}"})

    yield _stream_line({"type": "done", "updated": updated, "failed": failed, "total": total})


class RemoveVideoFromListingsRequest(BaseModel):
    item_ids: List[str] = Field(default_factory=list, description="Item IDs (listing numbers) or listing URLs.")


async def _remove_video_from_listings_stream(
    item_ids: List[str],
    access_token: str,
) -> AsyncIterator[bytes]:
    """Yield NDJSON progress; final event is 'done' (updated, failed, skipped) or 'error'."""
    if not item_ids:
        yield _stream_line({"type": "error", "detail": "At least one item ID is required."})
        return

    resolved: List[str] = []
    seen: set[str] = set()
    for x in item_ids:
        s = (x or "").strip()
        if not s:
            continue
        iid = _extract_item_id(s)
        if iid is None and s.isdigit() and 9 <= len(s) <= 14:
            iid = s
        if iid and iid not in seen:
            seen.add(iid)
            resolved.append(iid)
    if not resolved:
        yield _stream_line(
            {"type": "error", "detail": "No valid item IDs (use 9–14 digit listing numbers or listing URLs)."}
        )
        return

    total = len(resolved)
    updated = 0
    skipped = 0
    failed: List[str] = []

    for i, item_id in enumerate(resolved):
        yield _stream_line({"type": "progress", "message": f"Listing {i + 1}/{total} (item {item_id})…"})
        try:
            get_item_result = await trading_get_item(access_token, item_id)
            vids = get_item_result.get("video_ids") if isinstance(get_item_result, dict) else None
            has_video = isinstance(vids, list) and len(vids) > 0
            if not has_video:
                skipped += 1
                yield _stream_line({"type": "progress", "message": f"No video on {item_id} — skipped."})
                continue
            await trading_remove_video_from_item(access_token, item_id)
            updated += 1
        except Exception as e:
            logger.warning("listing_video: remove video item_id=%s failed: %s", item_id, e)
            failed.append(item_id)
            yield _stream_line({"type": "progress", "message": f"Failed: {item_id} — {e!s}"})

    yield _stream_line(
        {"type": "done", "updated": updated, "failed": failed, "skipped": skipped, "total": total}
    )


@router.post("/remove-video-from-listings")
async def remove_video_from_listings(
    body: RemoveVideoFromListingsRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Remove listing video via Trading API ReviseFixedPriceItem DeletedField (CSV/legacy listings).
    Body: { "item_ids": ["136528644539", ...] }. Streams NDJSON progress.
    """
    item_ids = [x.strip() for x in (body.item_ids or []) if x and str(x).strip()]
    if not item_ids:
        raise HTTPException(status_code=400, detail="At least one item ID is required.")

    try:
        access_token = await get_ebay_access_token(db)
    except Exception as e:
        logger.exception("listing_video: get_ebay_access_token failed")
        raise HTTPException(status_code=503, detail=f"eBay auth failed: {e!s}")

    return StreamingResponse(
        _remove_video_from_listings_stream(item_ids, access_token),
        media_type="application/x-ndjson",
    )


@router.post("/add-video-to-listings")
async def add_video_to_listings(
    body: AddVideoToListingsRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Add a video to listing(s) via Trading API ReviseFixedPriceItem (for CSV/legacy listings).
    Body: { "video_id": "...", "item_ids": ["136528644539", ...] }. Streams NDJSON progress.
    """
    video_id = (body.video_id or "").strip()
    item_ids = [x.strip() for x in (body.item_ids or []) if x and str(x).strip()]
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id is required.")
    if not item_ids:
        raise HTTPException(status_code=400, detail="At least one item ID is required.")

    try:
        access_token = await get_ebay_access_token(db)
    except Exception as e:
        logger.exception("listing_video: get_ebay_access_token failed")
        raise HTTPException(status_code=503, detail=f"eBay auth failed: {e!s}")

    return StreamingResponse(
        _add_video_to_listings_stream(video_id, item_ids, access_token),
        media_type="application/x-ndjson",
    )


@router.get("/video-id", response_model=VideoIdResponse)
async def get_video_id(
    item_number: str = Query(..., min_length=1, description="Listing URL or item number (e.g. 136528644539)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get video ID(s) for a listing. Pass a listing URL or item number only.
    Uses Trading API GetItem; returns video IDs from VideoDetails when present (e.g. CSV-uploaded listings).
    """
    input_str = (item_number or "").strip()
    if not input_str:
        raise HTTPException(status_code=400, detail="Provide a listing URL or item number.")

    item_id = _extract_item_id(input_str)
    if item_id is None:
        raise HTTPException(
            status_code=400,
            detail="Enter a listing URL or item number (e.g. 136528644539 or https://www.ebay.co.uk/itm/136528644539).",
        )

    try:
        access_token = await get_ebay_access_token(db)
    except Exception as e:
        logger.exception("listing_video: get_ebay_access_token failed")
        raise HTTPException(status_code=503, detail=f"eBay auth failed: {e!s}")

    # Item number or URL: GetItem (and fallback search if needed), return video IDs from GetItem or getInventoryItem.
    logger.info("listing_video: get_video_id item_id=%s", item_id)
    try:
        get_item_result = await trading_get_item(access_token, item_id)
    except httpx.HTTPStatusError as e:
        logger.warning("listing_video: trading_get_item failed status=%s body=%s", e.response.status_code, (e.response.text or "")[:300])
        raise HTTPException(
            status_code=404,
            detail=f"Listing {item_id} not found. Check the item number and that EBAY_MARKETPLACE_ID matches the listing site (e.g. EBAY_GB for ebay.co.uk).",
        )
    except Exception as e:
        logger.exception("listing_video: trading_get_item unexpected")
        raise HTTPException(status_code=502, detail=f"GetItem error: {e!s}")

    sku = get_item_result.get("sku") if isinstance(get_item_result.get("sku"), str) else None
    sku = (sku or "").strip() or None
    title = (get_item_result.get("title") or "").strip() or None
    video_ids_from_get_item = get_item_result.get("video_ids")
    if isinstance(video_ids_from_get_item, list) and len(video_ids_from_get_item) > 0:
        logger.info("listing_video: returning video_ids from GetItem (legacy/CSV listing) item_id=%s", item_id)
        return VideoIdResponse(item_number=item_id, video_ids=video_ids_from_get_item, title=title, sku=sku)

    # GetItem sometimes doesn't return SKU even when the listing has one. Fallback: search inventory for this listing ID.
    if not sku:
        logger.info("listing_video: GetItem returned no SKU, searching inventory for listingId=%s", item_id)
        limit = 100
        for page in range(50):
            try:
                inv_resp = await get_inventory_items(access_token, limit=limit, offset=page)
            except Exception as e:
                logger.warning("listing_video: get_inventory_items failed: %s", e)
                break
            items = inv_resp.get("inventoryItems") or []
            if not isinstance(items, list):
                items = []
            for it in items:
                s = (it.get("sku") or "").strip() if isinstance(it, dict) else None
                if not s:
                    continue
                try:
                    offers_resp = await get_offers(access_token, s)
                    for o in (offers_resp.get("offers") or []):
                        if not isinstance(o, dict):
                            continue
                        listing = o.get("listing") or {}
                        lid = listing.get("listingId")
                        if lid is not None and str(lid).strip() == item_id:
                            sku = s
                            logger.info("listing_video: found listingId=%s -> sku=%s", item_id, sku)
                            break
                    if sku:
                        break
                except Exception as e:
                    logger.debug("listing_video: get_offers(%s) failed: %s", s, e)
            if sku:
                break
            if len(items) < limit:
                break
            total = inv_resp.get("total", 0)
            try:
                total_int = int(total) if total is not None else 0
            except (TypeError, ValueError):
                total_int = 0
            if total_int and (page + 1) * limit >= total_int:
                break
        if not sku:
            raise HTTPException(
                status_code=404,
                detail=f"Listing {item_id} has no SKU in GetItem and was not found in your inventory search. If you know the SKU (e.g. uke03), you can get video IDs via Inventory API for that SKU.",
            )

    try:
        item = await get_inventory_item(access_token, sku)
    except Exception as e:
        logger.warning("listing_video: get_inventory_item(sku=%s) failed: %s", sku, e)
        raise HTTPException(status_code=502, detail=f"Could not load inventory for SKU: {e!s}")

    product = item.get("product") or {}
    video_ids = list(product.get("videoIds") or [])
    if not isinstance(video_ids, list):
        video_ids = [video_ids] if video_ids else []
    video_ids = [str(v).strip() for v in video_ids if v]
    title = title or (product.get("title") or "").strip() or None

    logger.info("listing_video: success item_id=%s video_ids=%s", item_id, video_ids)
    return VideoIdResponse(item_number=item_id, video_ids=video_ids, title=title, sku=sku)


# ---------------------------------------------------------------------------
# Persistent job system
# ---------------------------------------------------------------------------
# Design:
#   POST /start-add-video-job  → creates job + item rows, fires asyncio task, returns job_id
#   GET  /jobs/{job_id}        → returns job status + counters + last N log lines
#   GET  /jobs/{job_id}/logs   → all log lines (paginated via ?after_id=)
#
# The worker runs fully detached (asyncio.create_task) so disconnect / sleep
# does not abort it.  All state is in Postgres so the UI can reconnect any time.
# ---------------------------------------------------------------------------

_MAX_ATTEMPTS = 4           # initial + 3 retries
_CONCURRENCY  = 3           # parallel eBay Trading API calls
_RETRY_DELAYS = [2, 4, 8]   # seconds between retry rounds
_job_locks: dict[str, asyncio.Lock] = {}


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)  # store naive UTC


def _make_job_id() -> str:
    return secrets.token_hex(16)


# --- Pydantic request / response models ---

class StartAddVideoJobRequest(BaseModel):
    video_id: str
    # Exactly one of sku or item_ids must be provided
    sku: Optional[str] = None
    item_ids: Optional[List[str]] = None
    marketplace_id: Optional[str] = None


class JobStatusResponse(BaseModel):
    job_id: str
    mode: str
    sku: Optional[str]
    video_id: str
    status: str
    total: int
    updated_count: int
    skipped_count: int
    failed_count: int
    error_message: Optional[str]
    created_at: str
    updated_at: str
    recent_logs: List[str] = Field(default_factory=list)


class JobLogsResponse(BaseModel):
    job_id: str
    logs: List[dict]   # [{id, message, created_at}]


# --- Internal helpers ---

async def _log(session: AsyncSession, job_id: str, msg: str) -> None:
    session.add(ListingVideoJobLog(job_id=job_id, message=msg, created_at=_now()))


async def _job_set_status(session: AsyncSession, job_id: str, status: str, **extra) -> None:
    vals = {"status": status, "updated_at": _now(), **extra}
    await session.execute(
        update(ListingVideoJob).where(ListingVideoJob.job_id == job_id).values(**vals)
    )


async def _item_set(session: AsyncSession, job_id: str, item_id: str,
                    status: str, attempt_count: int, last_error: Optional[str] = None) -> None:
    await session.execute(
        update(ListingVideoJobItem)
        .where(ListingVideoJobItem.job_id == job_id,
               ListingVideoJobItem.item_id == item_id)
        .values(status=status, attempt_count=attempt_count,
                last_error=last_error, updated_at=_now())
    )


async def _refresh_counters(session: AsyncSession, job_id: str) -> None:
    """Recount updated/skipped/failed from item rows and persist."""
    result = await session.execute(
        select(ListingVideoJobItem.status)
        .where(ListingVideoJobItem.job_id == job_id)
    )
    statuses = [r[0] for r in result.all()]
    await session.execute(
        update(ListingVideoJob)
        .where(ListingVideoJob.job_id == job_id)
        .values(
            updated_count=sum(1 for s in statuses if s == "done"),
            skipped_count=sum(1 for s in statuses if s == "skipped"),
            failed_count=sum(1 for s in statuses if s == "failed"),
            updated_at=_now(),
        )
    )


# --- The actual worker (runs as a background task) ---

async def _process_item(
    job_id: str,
    item_id: str,
    video_id: str,
    access_token: str,
    semaphore: asyncio.Semaphore,
    marketplace_id: Optional[str],  # per-item marketplace (site for ReviseFixedPriceItem)
) -> str:
    """
    Process one listing: GetItem → skip if already has video → Revise.
    Returns final status: 'done' | 'skipped' | 'failed:<msg>'
    """
    async with semaphore:
        # Check current video IDs
        try:
            gi = await trading_get_item(access_token, item_id)
            existing = gi.get("video_ids") or []
            if video_id in existing:
                return "skipped"
        except Exception as e:
            logger.warning("listing_video job %s: GetItem %s failed: %s", job_id, item_id, e)
            # Don't skip on GetItem error – still attempt the revise

        try:
            await trading_revise_fixed_price_item(access_token, item_id, video_id, marketplace_id)
            return "done"
        except Exception as e:
            msg = str(e).strip() or type(e).__name__
            return f"failed:{msg}"


async def _run_job_worker(job_id: str) -> None:
    """
    Detached async task.  Reads/writes DB exclusively through its own sessions.
    Supports resume: picks up pending/retryable items if called again on the same job_id.
    """
    log = logging.getLogger(__name__)
    if job_id not in _job_locks:
        _job_locks[job_id] = asyncio.Lock()
    async with _job_locks[job_id]:
        await _run_job_worker_inner(job_id, log)


async def _run_job_worker_inner(job_id: str, log: logging.Logger) -> None:
    try:
        async with async_session_maker() as db:
            result = await db.execute(
                select(ListingVideoJob).where(ListingVideoJob.job_id == job_id)
            )
            job = result.scalar_one_or_none()
        if job is None:
            log.error("listing_video job %s: not found in DB", job_id)
            return

        video_id = job.video_id
        marketplace_id = job.marketplace_id
        access_token: str

        # Get a fresh access token (valid for ~2h; for very large jobs we refresh per-round)
        async with async_session_maker() as db:
            access_token = await get_ebay_access_token(db)

        # --- Phase 1: resolve item IDs (only needed if no items inserted yet) ---
        async with async_session_maker() as db:
            existing_count_result = await db.execute(
                select(ListingVideoJobItem).where(ListingVideoJobItem.job_id == job_id).limit(1)
            )
            has_items = existing_count_result.scalar_one_or_none() is not None

        if not has_items:
            item_ids: List[str] = []
            if job.mode == "sku":
                sku = job.sku or ""
                # Primary site first; other configured sites only if primary returns nothing.
                # GetSellerList+SKUArray returns the same ItemIDs across SiteIDs for this
                # seller, so scanning GB+DE+US every time is redundant.
                configured = [
                    m.strip().upper()
                    for m in settings.EBAY_SCAN_MARKETPLACES.split(",")
                    if m.strip()
                ]
                primary = (settings.EBAY_MARKETPLACE_ID or "EBAY_GB").strip().upper()
                fallbacks = [m for m in configured if m != primary]
                scan_order = [primary] + fallbacks
                seen_ids: set = set()
                scan_error: str | None = None

                async with async_session_maker() as db:
                    await _job_set_status(db, job_id, "scanning")
                    await _log(
                        db, job_id,
                        f"Looking up SKU {sku} on {primary.replace('EBAY_', '')}"
                        + (f" (fallback: {', '.join(m.replace('EBAY_', '') for m in fallbacks)} if empty)…"
                           if fallbacks else "…"),
                    )
                    await db.commit()

                for i, mkt in enumerate(scan_order):
                    if i > 0 and seen_ids:
                        break  # primary (or earlier site) already found listings
                    mkt_label = mkt.replace("EBAY_", "")
                    if i > 0:
                        async with async_session_maker() as db:
                            await _log(db, job_id, f"No listings on previous site — trying {mkt_label}…")
                            await db.commit()
                    site_returned = 0
                    try:
                        async for payload in trading_get_seller_list_by_sku(
                            access_token, sku, mkt, yield_page_progress=False
                        ):
                            if isinstance(payload, dict):
                                continue
                            site_returned = len(payload)
                            for iid in payload:
                                if iid not in seen_ids:
                                    seen_ids.add(iid)
                                    item_ids.append((iid, mkt))
                    except Exception as e:
                        detail = str(e).strip() or type(e).__name__
                        scan_error = f"{mkt_label}: scan failed — {detail}"
                        async with async_session_maker() as db:
                            await _log(db, job_id, scan_error)
                            await db.commit()
                        continue

                    async with async_session_maker() as db:
                        await _log(
                            db, job_id,
                            f"{mkt_label}: found {site_returned} listing(s).",
                        )
                        await db.commit()

                if not item_ids:
                    err = scan_error or f"No listings found for SKU '{sku}' on any marketplace."
                    async with async_session_maker() as db:
                        await _job_set_status(db, job_id, "error", error_message=err)
                        await _log(db, job_id, err + " Check Custom Label matches.")
                        await db.commit()
                    return
            else:
                # item_ids mode: already stored via job creation – fetch from job row extra column?
                # We store them directly as job items at creation time, so this path shouldn't
                # normally be reached. But handle gracefully.
                async with async_session_maker() as db:
                    await _job_set_status(db, job_id, "error",
                                          error_message="No items found and mode is not sku.")
                    await db.commit()
                return

            # Insert item rows — item_ids is list of (item_id, marketplace_id) tuples for SKU mode,
            # or list of bare item_id strings for item_ids mode (set below).
            now = _now()
            async with async_session_maker() as db:
                for entry in item_ids:
                    if isinstance(entry, tuple):
                        iid, item_mkt = entry
                    else:
                        iid, item_mkt = entry, None
                    db.add(ListingVideoJobItem(
                        job_id=job_id, item_id=iid, marketplace_id=item_mkt,
                        status="pending", attempt_count=0, updated_at=now,
                    ))
                await db.execute(
                    update(ListingVideoJob)
                    .where(ListingVideoJob.job_id == job_id)
                    .values(total=len(item_ids), status="running", updated_at=now)
                )
                await _log(db, job_id, f"Scan complete: {len(item_ids)} listing(s) to process.")
                await db.commit()
        else:
            # Resume: set running
            async with async_session_maker() as db:
                await _job_set_status(db, job_id, "running")
                await _log(db, job_id, "Resuming job…")
                await db.commit()

        # --- Phase 2: process each pending item with bounded concurrency and retries ---
        semaphore = asyncio.Semaphore(_CONCURRENCY)

        async with async_session_maker() as db:
            r = await db.execute(select(ListingVideoJob).where(ListingVideoJob.job_id == job_id))
            job_total = r.scalar_one().total or 0

        for attempt in range(1, _MAX_ATTEMPTS + 1):
            async with async_session_maker() as db:
                result = await db.execute(
                    select(ListingVideoJobItem)
                    .where(
                        ListingVideoJobItem.job_id == job_id,
                        ListingVideoJobItem.status == "pending",
                    )
                    .order_by(ListingVideoJobItem.id.asc())
                )
                pending_items = list(result.scalars().all())

            if not pending_items:
                break

            n_pending = len(pending_items)
            if attempt > 1:
                delay = _RETRY_DELAYS[min(attempt - 2, len(_RETRY_DELAYS) - 1)]
                async with async_session_maker() as db:
                    await _log(
                        db, job_id,
                        f"Retry round {attempt}/{_MAX_ATTEMPTS}: "
                        f"{n_pending} listing(s) still pending, waiting {delay}s…",
                    )
                    await db.commit()
                await asyncio.sleep(delay)
                try:
                    async with async_session_maker() as db:
                        access_token = await get_ebay_access_token(db)
                except Exception:
                    pass
            else:
                async with async_session_maker() as db:
                    await _log(db, job_id, f"Processing {n_pending} listing(s)…")
                    await db.commit()

            already_done = max(0, job_total - n_pending)

            async def _run_one(item: ListingVideoJobItem):
                try:
                    outcome = await _process_item(
                        job_id, item.item_id, video_id, access_token,
                        semaphore, item.marketplace_id or marketplace_id,
                    )
                except Exception as e:
                    outcome = f"failed:{e}"
                return item, outcome

            task_list = [asyncio.create_task(_run_one(item)) for item in pending_items]
            results_this_round = {"done": 0, "skipped": 0, "failed": 0}
            finished_in_round = 0

            for fut in asyncio.as_completed(task_list):
                item, outcome = await fut

                finished_in_round += 1
                row = already_done + finished_in_round
                total_label = job_total or n_pending

                if outcome == "skipped":
                    final_status = "skipped"
                    last_error = None
                    results_this_round["skipped"] += 1
                    status_label = "skipped (already has this video)"
                elif outcome == "done":
                    final_status = "done"
                    last_error = None
                    results_this_round["done"] += 1
                    status_label = "updated"
                else:
                    err_msg = (
                        outcome[len("failed:"):]
                        if isinstance(outcome, str) and outcome.startswith("failed:")
                        else str(outcome)
                    )
                    if attempt < _MAX_ATTEMPTS:
                        final_status = "pending"
                        status_label = f"failed — {err_msg} (will retry)"
                    else:
                        final_status = "failed"
                        results_this_round["failed"] += 1
                        status_label = f"failed — {err_msg}"
                    last_error = err_msg

                async with async_session_maker() as db:
                    await _item_set(
                        db, job_id, item.item_id, final_status,
                        item.attempt_count + 1, last_error,
                    )
                    await _log(
                        db, job_id,
                        f"[{row}/{total_label}] {item.item_id} — {status_label}",
                    )
                    if finished_in_round % 5 == 0 or finished_in_round == n_pending:
                        await _refresh_counters(db, job_id)
                    await db.commit()

            async with async_session_maker() as db:
                await _log(
                    db, job_id,
                    f"Round {attempt}: updated={results_this_round['done']} "
                    f"skipped={results_this_round['skipped']} "
                    f"failed_this_round={results_this_round['failed']}",
                )
                await _refresh_counters(db, job_id)
                await db.commit()

            # Do not abort when a round updates/skips nothing. Transient eBay
            # errors (rate limit, timeout) commonly fail every concurrent
            # revise; items stay pending and the next attempt waits _RETRY_DELAYS.
            # Permanent failures are marked failed on the last attempt above.

        # --- Phase 3: finalize ---
        async with async_session_maker() as db:
            r = await db.execute(
                select(ListingVideoJob).where(ListingVideoJob.job_id == job_id)
            )
            job_final = r.scalar_one()
            total = job_final.total
            updated = job_final.updated_count
            skipped = job_final.skipped_count
            failed = job_final.failed_count
            await _log(db, job_id,
                       f"Done. Updated {updated}/{total}, skipped {skipped}, failed {failed}.")
            await _job_set_status(db, job_id, "done")
            await db.commit()

    except Exception as exc:
        log.exception("listing_video job %s: unexpected error in worker", job_id)
        try:
            async with async_session_maker() as db:
                await _job_set_status(db, job_id, "error",
                                      error_message=f"Worker crashed: {exc!s}")
                await _log(db, job_id, f"Worker crashed: {exc!s}")
                await db.commit()
        except Exception:
            pass


# --- Endpoints ---

@router.post("/start-add-video-job")
async def start_add_video_job(
    body: StartAddVideoJobRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Start a persistent add-video job.  Returns {job_id} immediately.
    The worker runs detached; poll GET /jobs/{job_id} for status.

    Body (one mode required):
      - SKU mode:      { video_id, sku, marketplace_id? }
      - Item-ID mode:  { video_id, item_ids: [...] }
    """
    video_id = (body.video_id or "").strip()
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id is required.")

    sku = (body.sku or "").strip() or None
    raw_ids = body.item_ids or []
    marketplace_id = (body.marketplace_id or "").strip() or None

    if sku:
        mode = "sku"
        item_ids: List[str] = []
    elif raw_ids:
        mode = "item_ids"
        item_ids = _parse_item_ids("\n".join(raw_ids))
        if not item_ids:
            raise HTTPException(status_code=400, detail="No valid item IDs provided.")
    else:
        raise HTTPException(status_code=400, detail="Provide either sku or item_ids.")

    # Validate eBay auth before creating job
    try:
        await get_ebay_access_token(db)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"eBay auth failed: {e!s}")

    job_id = _make_job_id()
    now = _now()
    job = ListingVideoJob(
        job_id=job_id,
        mode=mode,
        sku=sku,
        video_id=video_id,
        marketplace_id=marketplace_id,
        status="pending",
        total=len(item_ids) if mode == "item_ids" else 0,
        updated_count=0,
        skipped_count=0,
        failed_count=0,
        created_at=now,
        updated_at=now,
    )
    db.add(job)

    if mode == "item_ids":
        for iid in item_ids:
            db.add(ListingVideoJobItem(
                job_id=job_id, item_id=iid, status="pending",
                attempt_count=0, updated_at=now,
            ))

    await db.commit()

    # Fire detached worker
    asyncio.create_task(_run_job_worker(job_id))

    return {"job_id": job_id, "mode": mode, "total": len(item_ids), "status": "pending"}


@router.get("/jobs/{job_id}", response_model=JobStatusResponse)
async def get_job_status(
    job_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Return job status + counters + last 50 log lines.
    Poll every few seconds from the UI.
    """
    result = await db.execute(
        select(ListingVideoJob).where(ListingVideoJob.job_id == job_id)
    )
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    logs_result = await db.execute(
        select(ListingVideoJobLog)
        .where(ListingVideoJobLog.job_id == job_id)
        .order_by(ListingVideoJobLog.id.desc())
        .limit(50)
    )
    log_rows = logs_result.scalars().all()
    recent_logs = [r.message for r in reversed(log_rows)]

    return JobStatusResponse(
        job_id=job.job_id,
        mode=job.mode,
        sku=job.sku,
        video_id=job.video_id,
        status=job.status,
        total=job.total,
        updated_count=job.updated_count,
        skipped_count=job.skipped_count,
        failed_count=job.failed_count,
        error_message=job.error_message,
        created_at=job.created_at.isoformat() if job.created_at else "",
        updated_at=job.updated_at.isoformat() if job.updated_at else "",
        recent_logs=recent_logs,
    )


@router.get("/jobs/{job_id}/logs", response_model=JobLogsResponse)
async def get_job_logs(
    job_id: str,
    after_id: int = Query(0, description="Return only log rows with id > after_id (for incremental polling)"),
    db: AsyncSession = Depends(get_db),
):
    """Return log lines for a job, optionally only newer than after_id."""
    result = await db.execute(
        select(ListingVideoJob).where(ListingVideoJob.job_id == job_id)
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Job not found.")

    logs_result = await db.execute(
        select(ListingVideoJobLog)
        .where(
            ListingVideoJobLog.job_id == job_id,
            ListingVideoJobLog.id > after_id,
        )
        .order_by(ListingVideoJobLog.id.asc())
        .limit(500)
    )
    log_rows = logs_result.scalars().all()
    return JobLogsResponse(
        job_id=job_id,
        logs=[
            {"id": r.id, "message": r.message, "created_at": r.created_at.isoformat()}
            for r in log_rows
        ],
    )
