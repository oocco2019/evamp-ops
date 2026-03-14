"""
Get video ID from an eBay listing by item number or listing URL.
Uses Trading API GetItem(ItemID) then Inventory API getInventoryItem(sku) for videoIds.
"""
import json
import re
import logging
from typing import List, AsyncIterator

import httpx
from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.ebay_auth import get_ebay_access_token
from app.services.ebay_client import (
    trading_get_item,
    trading_revise_fixed_price_item,
    trading_get_seller_list_by_sku,
    get_inventory_item,
    get_inventory_items,
    get_offers,
    create_or_replace_inventory_item,
)

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
        yield _stream_line({"type": "error", "detail": f"Could not get listings for SKU '{sku}': {e!s}"})
        return

    if not item_ids:
        yield _stream_line({"type": "error", "detail": f"No listings found for SKU '{sku}'. Check the SKU and that you have active listings with that SKU on this site."})
        return

    total = len(item_ids)
    yield _stream_line({"type": "listing_count", "count": total})
    yield _stream_line({"type": "progress", "message": f"Found {total} listing(s). Adding video…"})

    updated = 0
    failed: List[str] = []
    for i, item_id in enumerate(item_ids):
        yield _stream_line({"type": "progress", "message": f"Revising listing {i + 1}/{total} (item {item_id})…"})
        try:
            await trading_revise_fixed_price_item(access_token, item_id, video_id, marketplace_id)
            updated += 1
        except Exception as e:
            logger.warning("listing_video: revise item_id=%s failed: %s", item_id, e)
            failed.append(item_id)
            yield _stream_line({"type": "progress", "message": f"Failed: {item_id} — {e!s}"})

    yield _stream_line({"type": "done", "sku": sku, "updated": updated, "failed": failed, "total": total})


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
        return VideoIdResponse(item_number=item_id, video_ids=video_ids_from_get_item, title=title)

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
    return VideoIdResponse(item_number=item_id, video_ids=video_ids, title=title)
