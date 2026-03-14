"""
Get video ID from an eBay listing by item number or listing URL.
Uses Trading API GetItem(ItemID) then Inventory API getInventoryItem(sku) for videoIds.
"""
import re
import logging
from typing import List

import httpx
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.ebay_auth import get_ebay_access_token
from app.services.ebay_client import trading_get_item, get_inventory_item, get_inventory_items, get_offers

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


@router.get("/video-id", response_model=VideoIdResponse)
async def get_video_id(
    item_number: str = Query(..., min_length=1, description="eBay item number, listing URL, or SKU (e.g. uke03)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Get video ID(s). Pass an item number, listing URL, or SKU.
    - Item number/URL: GetItem (and inventory search fallback) → SKU → getInventoryItem(sku) → videoIds.
    - SKU (e.g. uke03): getInventoryItem(sku) → videoIds. One inventory item per SKU; all listings with that SKU share the same videoIds (no per-listing loop).
    """
    input_str = (item_number or "").strip()
    if not input_str:
        raise HTTPException(status_code=400, detail="Provide an item number, listing URL, or SKU.")

    try:
        access_token = await get_ebay_access_token(db)
    except Exception as e:
        logger.exception("listing_video: get_ebay_access_token failed")
        raise HTTPException(status_code=503, detail=f"eBay auth failed: {e!s}")

    item_id = _extract_item_id(input_str)

    if item_id is None:
        # Treat as SKU: one getInventoryItem call. All listings with this SKU share the same inventory item and same videoIds.
        logger.info("listing_video: get_video_id by SKU sku=%s", input_str)
        try:
            item = await get_inventory_item(access_token, input_str)
        except Exception as e:
            logger.warning("listing_video: get_inventory_item(sku=%s) failed: %s", input_str, e)
            raise HTTPException(status_code=404, detail=f"SKU '{input_str}' not found in your inventory.")
        product = item.get("product") or {}
        video_ids = list(product.get("videoIds") or [])
        if not isinstance(video_ids, list):
            video_ids = [video_ids] if video_ids else []
        video_ids = [str(v).strip() for v in video_ids if v]
        title = (product.get("title") or "").strip() or None
        logger.info("listing_video: success by SKU sku=%s video_ids=%s", input_str, video_ids)
        return VideoIdResponse(item_number=input_str, video_ids=video_ids, title=title)

    # Item number or URL: resolve to SKU via GetItem (and fallback search), then getInventoryItem.
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
