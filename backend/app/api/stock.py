"""
Stock API: eBay OAuth, order import, SKU CRUD (SM02, SM03).
"""
import logging
from datetime import datetime, date, timedelta
from typing import List, Optional
from urllib.parse import quote
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, Field
from decimal import Decimal

from app.core.database import get_db
from app.core.config import settings as app_settings
from app.core.security import encryption_service
from app.models.settings import APICredential
from app.models.stock import Order, LineItem, SKU
from app.services.ebay_client import (
    get_authorization_url,
    exchange_code_for_token,
    refresh_access_token,
    fetch_all_orders,
    fetch_orders_modified_since,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# === eBay OAuth ===

class AuthUrlResponse(BaseModel):
    url: str
    state: str


@router.get("/ebay/auth-url", response_model=AuthUrlResponse)
async def get_ebay_auth_url():
    """
    Return the URL to send the user to for eBay OAuth consent.
    Frontend redirects user to this URL; after consent, eBay redirects to callback.
    """
    from app.core.config import settings as s
    if not (s.EBAY_APP_ID and s.EBAY_REDIRECT_URI):
        raise HTTPException(
            status_code=500,
            detail="EBAY_APP_ID and EBAY_REDIRECT_URI must be set in .env (RuName, not the full URL).",
        )
    # RuName must not look like a URL (eBay expects the short RuName string)
    if s.EBAY_REDIRECT_URI.startswith("http://") or s.EBAY_REDIRECT_URI.startswith("https://"):
        raise HTTPException(
            status_code=500,
            detail="EBAY_REDIRECT_URI must be the RuName from eBay (e.g. AppName-AppName-PRD-xxx), not the full https URL.",
        )
    state = __import__("secrets").token_urlsafe(32)
    url = get_authorization_url(state=state)
    return AuthUrlResponse(url=url, state=state)


@router.get("/ebay/config-check")
async def ebay_config_check():
    """
    Safe check: are EBAY_APP_ID and EBAY_REDIRECT_URI set and non-empty?
    Returns lengths only (no secrets). Use this to verify .env / Docker env is loaded.
    """
    from app.core.config import settings as s
    app_id = (s.EBAY_APP_ID or "").strip()
    redirect_uri = (s.EBAY_REDIRECT_URI or "").strip()
    return {
        "EBAY_APP_ID": {
            "set": bool(app_id),
            "length": len(app_id),
            "ok": bool(app_id),
        },
        "EBAY_REDIRECT_URI": {
            "set": bool(redirect_uri),
            "length": len(redirect_uri),
            "looks_like_url": redirect_uri.startswith("http://") or redirect_uri.startswith("https://"),
            "ok": bool(redirect_uri) and not (redirect_uri.startswith("http://") or redirect_uri.startswith("https://")),
        },
        "ready_for_auth_url": bool(app_id) and bool(redirect_uri) and not (
            redirect_uri.startswith("http://") or redirect_uri.startswith("https://")
        ),
        "hint": "If set is false, the backend did not receive the env var (e.g. add EBAY_REDIRECT_URI to docker-compose environment and restart).",
    }


@router.get("/ebay/ngrok-check")
async def ebay_ngrok_check(request: Request):
    """
    Reachability check: returns the Host header of this request.
    Call this via your ngrok URL (e.g. https://your-subdomain.ngrok-free.dev/api/stock/ebay/ngrok-check).
    If you see your ngrok host in the response, the request reached the backend.
    """
    host = request.headers.get("host", "")
    return {
        "ok": True,
        "host": host,
        "message": "If host matches your ngrok URL, the backend is reachable via ngrok.",
        "callback_path": "/api/stock/ebay/callback",
        "hint": "In eBay Developer Portal, set 'Your auth accepted URL' to https://<host>/api/stock/ebay/callback (use the host shown above).",
    }


@router.get("/ebay/debug")
async def ebay_debug():
    """
    Help debug OAuth: shows what we're sending (no secrets). Only in DEBUG mode.
    """
    from app.core.config import settings as s
    if not s.DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "EBAY_APP_ID_set": bool(s.EBAY_APP_ID),
        "EBAY_REDIRECT_URI_set": bool(s.EBAY_REDIRECT_URI),
        "EBAY_REDIRECT_URI_value": s.EBAY_REDIRECT_URI[:20] + "..." if len(s.EBAY_REDIRECT_URI or "") > 20 else (s.EBAY_REDIRECT_URI or ""),
        "EBAY_AUTH_URL": s.EBAY_AUTH_URL,
        "scope_used": "sell.fulfillment.readonly",
        "hint": "RuName must be Production RuName if you use auth.ebay.com (production). No spaces or quotes in .env.",
    }


@router.get("/ebay/callback")
async def ebay_oauth_callback(
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    error_description: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    eBay redirects here after user grants consent. Exchange code for tokens,
    store refresh_token (encrypted), redirect to frontend.
    """
    base_url = app_settings.FRONTEND_URL.rstrip("/")
    if error:
        redirect_url = f"{base_url}/settings?ebay_error={error_description or error}"
        return RedirectResponse(url=redirect_url, status_code=302)

    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")

    try:
        token_data = await exchange_code_for_token(code)
    except Exception as exc:
        detail = ""
        try:
            import httpx
            if isinstance(exc, httpx.HTTPStatusError):
                try:
                    body = exc.response.json()
                    detail = body.get("error_description") or body.get("error") or exc.response.text or ""
                except Exception:
                    detail = exc.response.text or str(exc)
                logger.warning("eBay token exchange failed: %s %s", exc.response.status_code, detail)
            else:
                logger.exception("eBay token exchange failed")
                detail = str(exc)
        except Exception:
            logger.exception("eBay token exchange failed")
            detail = str(exc)
        safe_detail = quote((detail or "unknown")[:300])
        redirect_url = f"{base_url}/settings?ebay_error=token_exchange_failed&ebay_error_detail={safe_detail}"
        return RedirectResponse(url=redirect_url, status_code=302)

    refresh_token = token_data.get("refresh_token")
    if not refresh_token:
        redirect_url = f"{base_url}/settings?ebay_error=no_refresh_token"
        return RedirectResponse(url=redirect_url, status_code=302)

    encrypted = encryption_service.encrypt(refresh_token)

    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == "ebay",
            APICredential.key_name == "refresh_token",
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.encrypted_value = encrypted
        existing.is_active = True
    else:
        db.add(APICredential(
            service_name="ebay",
            key_name="refresh_token",
            encrypted_value=encrypted,
            is_active=True,
        ))
    await db.commit()

    return RedirectResponse(url=f"{base_url}/settings?ebay_connected=1", status_code=302)


class eBayStatusResponse(BaseModel):
    connected: bool


@router.get("/ebay/status", response_model=eBayStatusResponse)
async def ebay_connection_status(db: AsyncSession = Depends(get_db)):
    """Check if eBay is connected (refresh token stored)."""
    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == "ebay",
            APICredential.key_name == "refresh_token",
            APICredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()
    return eBayStatusResponse(connected=cred is not None)


# === Import ===

class ImportRequest(BaseModel):
    mode: str = Field(..., description="full or incremental")


class ImportResponse(BaseModel):
    orders_added: int
    orders_updated: int
    line_items_added: int
    line_items_updated: int
    last_import: Optional[datetime] = None
    error: Optional[str] = None


async def _get_ebay_access_token(db: AsyncSession) -> str:
    """Get valid access token: from DB refresh_token, refresh if needed."""
    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == "ebay",
            APICredential.key_name == "refresh_token",
            APICredential.is_active == True,
        )
    )
    cred = result.scalar_one_or_none()
    if not cred:
        raise HTTPException(
            status_code=400,
            detail="eBay not connected. Connect eBay first in Settings.",
        )
    refresh_token = encryption_service.decrypt(cred.encrypted_value)
    token_data = await refresh_access_token(refresh_token)
    return token_data["access_token"]


@router.post("/import", response_model=ImportResponse)
async def run_import(
    body: ImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Run order import: full (last 90 days; eBay filter limit) or incremental (since last import).
    """
    if body.mode not in ("full", "incremental"):
        raise HTTPException(status_code=400, detail="mode must be 'full' or 'incremental'")

    try:
        access_token = await _get_ebay_access_token(db)
    except HTTPException:
        raise
    except Exception as e:
        return ImportResponse(
            orders_added=0, orders_updated=0, line_items_added=0, line_items_updated=0,
            error=str(e),
        )

    orders_added = 0
    orders_updated = 0
    line_items_added = 0
    line_items_updated = 0
    last_import = datetime.utcnow()

    try:
        if body.mode == "incremental":
            result = await db.execute(select(func.max(Order.last_modified)))
            max_modified = result.scalar()
            since = (max_modified or datetime(2000, 1, 1)) - timedelta(seconds=1)
            chunks = [await fetch_orders_modified_since(access_token, since)]
        else:
            end_date = datetime.utcnow()
            # eBay getOrders filter returns data from only the last 90 days; requesting older dates returns 400.
            start_date = end_date - timedelta(days=90)
            chunks = []
            current = start_date
            while current < end_date:
                chunk_end = min(current + timedelta(days=31), end_date)
                chunk_orders = await fetch_all_orders(access_token, current, chunk_end)
                chunks.append(chunk_orders)
                current = chunk_end

        for order_batch in chunks:
            for o in order_batch:
                result = await db.execute(
                    select(Order).where(Order.ebay_order_id == o["ebay_order_id"])
                )
                existing_order = result.scalar_one_or_none()
                if existing_order:
                    order_changed = (
                        existing_order.date != o["date"]
                        or existing_order.country != o["country"]
                        or existing_order.last_modified != o["last_modified"]
                    )
                    if order_changed:
                        existing_order.date = o["date"]
                        existing_order.country = o["country"]
                        existing_order.last_modified = o["last_modified"]
                        await db.flush()
                        orders_updated += 1
                    order_id = existing_order.order_id
                    result_li = await db.execute(select(LineItem).where(LineItem.order_id == order_id))
                    existing_items = {(li.ebay_line_item_id): li for li in result_li.scalars().all()}
                else:
                    new_order = Order(
                        ebay_order_id=o["ebay_order_id"],
                        date=o["date"],
                        country=o["country"],
                        last_modified=o["last_modified"],
                    )
                    db.add(new_order)
                    await db.flush()
                    orders_added += 1
                    order_id = new_order.order_id
                    existing_items = {}

                for li in o["line_items"]:
                    eid = li["ebay_line_item_id"]
                    if eid in existing_items:
                        line_changed = (
                            existing_items[eid].sku != li["sku"]
                            or existing_items[eid].quantity != li["quantity"]
                        )
                        if line_changed:
                            existing_items[eid].sku = li["sku"]
                            existing_items[eid].quantity = li["quantity"]
                            line_items_updated += 1
                    else:
                        db.add(LineItem(
                            order_id=order_id,
                            ebay_line_item_id=eid,
                            sku=li["sku"],
                            quantity=li["quantity"],
                        ))
                        line_items_added += 1

        await db.commit()
    except Exception as e:
        await db.rollback()
        return ImportResponse(
            orders_added=orders_added,
            orders_updated=orders_updated,
            line_items_added=line_items_added,
            line_items_updated=line_items_updated,
            last_import=last_import,
            error=str(e),
        )

    return ImportResponse(
        orders_added=orders_added,
        orders_updated=orders_updated,
        line_items_added=line_items_added,
        line_items_updated=line_items_updated,
        last_import=last_import,
    )


# === SKU CRUD ===

class SKUCreate(BaseModel):
    sku_code: str = Field(..., max_length=100)
    title: str = Field(..., max_length=255)
    landed_cost: Optional[Decimal] = None
    postage_price: Optional[Decimal] = None
    profit_per_unit: Optional[Decimal] = None
    currency: str = Field(default="USD", max_length=3)


class SKUUpdate(BaseModel):
    title: Optional[str] = Field(None, max_length=255)
    landed_cost: Optional[Decimal] = None
    postage_price: Optional[Decimal] = None
    profit_per_unit: Optional[Decimal] = None
    currency: Optional[str] = Field(None, max_length=3)


class SKUResponse(BaseModel):
    sku_code: str
    title: str
    landed_cost: Optional[Decimal]
    postage_price: Optional[Decimal]
    profit_per_unit: Optional[Decimal]
    currency: str

    model_config = {"from_attributes": True}


@router.get("/skus", response_model=List[SKUResponse])
async def list_skus(
    search: Optional[str] = Query(None, description="Search by SKU code or title"),
    db: AsyncSession = Depends(get_db),
):
    """List SKUs with optional search."""
    q = select(SKU)
    if search and search.strip():
        term = f"%{search.strip()}%"
        q = q.where((SKU.sku_code.ilike(term)) | (SKU.title.ilike(term)))
    q = q.order_by(SKU.sku_code)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/skus", response_model=SKUResponse, status_code=status.HTTP_201_CREATED)
async def create_sku(body: SKUCreate, db: AsyncSession = Depends(get_db)):
    """Create a SKU. Validates unique sku_code and numeric fields >= 0."""
    if body.landed_cost is not None and body.landed_cost < 0:
        raise HTTPException(status_code=400, detail="landed_cost must be >= 0")
    if body.postage_price is not None and body.postage_price < 0:
        raise HTTPException(status_code=400, detail="postage_price must be >= 0")
    if body.profit_per_unit is not None and body.profit_per_unit < 0:
        raise HTTPException(status_code=400, detail="profit_per_unit must be >= 0")

    result = await db.execute(select(SKU).where(SKU.sku_code == body.sku_code.strip()))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="SKU code already exists")

    sku = SKU(
        sku_code=body.sku_code.strip(),
        title=body.title.strip(),
        landed_cost=body.landed_cost,
        postage_price=body.postage_price,
        profit_per_unit=body.profit_per_unit,
        currency=(body.currency or "USD").strip().upper()[:3],
    )
    db.add(sku)
    await db.commit()
    await db.refresh(sku)
    return sku


@router.get("/skus/{sku_code}", response_model=SKUResponse)
async def get_sku(sku_code: str, db: AsyncSession = Depends(get_db)):
    """Get one SKU."""
    result = await db.execute(select(SKU).where(SKU.sku_code == sku_code))
    sku = result.scalar_one_or_none()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    return sku


@router.put("/skus/{sku_code}", response_model=SKUResponse)
async def update_sku(sku_code: str, body: SKUUpdate, db: AsyncSession = Depends(get_db)):
    """Update a SKU."""
    result = await db.execute(select(SKU).where(SKU.sku_code == sku_code))
    sku = result.scalar_one_or_none()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    if body.landed_cost is not None and body.landed_cost < 0:
        raise HTTPException(status_code=400, detail="landed_cost must be >= 0")
    if body.postage_price is not None and body.postage_price < 0:
        raise HTTPException(status_code=400, detail="postage_price must be >= 0")
    if body.profit_per_unit is not None and body.profit_per_unit < 0:
        raise HTTPException(status_code=400, detail="profit_per_unit must be >= 0")

    for k, v in body.model_dump(exclude_unset=True).items():
        if v is not None and k == "currency":
            setattr(sku, k, (v or "USD").strip().upper()[:3])
        else:
            setattr(sku, k, v)
    await db.commit()
    await db.refresh(sku)
    return sku


@router.delete("/skus/{sku_code}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_sku(sku_code: str, db: AsyncSession = Depends(get_db)):
    """Delete a SKU."""
    result = await db.execute(select(SKU).where(SKU.sku_code == sku_code))
    sku = result.scalar_one_or_none()
    if not sku:
        raise HTTPException(status_code=404, detail="SKU not found")
    await db.delete(sku)
    await db.commit()
