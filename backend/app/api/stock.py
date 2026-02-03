"""
Stock API: eBay OAuth, order import, SKU CRUD (SM02, SM03).
"""
import logging
from datetime import datetime, date, timedelta
from typing import List, Optional
from urllib.parse import quote, unquote
from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy import select, func, or_, case
from pydantic import BaseModel, Field
from decimal import Decimal

from app.core.database import get_db
from app.core.config import settings as app_settings
from app.core.security import encryption_service
from app.models.settings import APICredential, Warehouse
from app.models.stock import Order, LineItem, SKU, PurchaseOrder, POLineItem
from app.services.ebay_client import (
    get_authorization_url,
    exchange_code_for_token,
    refresh_access_token,
    fetch_all_orders,
    fetch_orders_modified_since,
    fetch_order_by_id,
    fetch_transactions_for_order,
    parse_net_order_earnings_from_transactions,
    parse_ad_fees_from_transactions,
    _parse_total_due_seller,
)
from app.services.ebay_auth import get_ebay_access_token

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


@router.get("/ebay/callback-url")
async def ebay_callback_url(request: Request):
    """
    Return the full callback URL to paste in eBay (Auth Accepted URL).
    Set CALLBACK_BASE_URL in .env to your tunnel URL (e.g. localhost.run). With localhost.run the URL is stable — set once in eBay.
    """
    from app.core.config import settings as s
    base = (s.CALLBACK_BASE_URL or "").strip().rstrip("/")
    if base:
        callback_url = f"{base}/api/stock/ebay/callback"
        hint = "Set once: Paste this in eBay Developer Portal → User Tokens → Auth Accepted URL."
    else:
        host = (request.headers.get("host") or "").split(":")[0]
        if host and host not in ("localhost", "127.0.0.1"):
            callback_url = f"https://{request.headers.get('host', host)}/api/stock/ebay/callback"
            hint = "You reached the backend via a public host. Paste this in eBay → Auth Accepted URL. To see this from localhost, set CALLBACK_BASE_URL in .env to your tunnel URL (e.g. localhost.run)."
        else:
            callback_url = ""
            hint = "Set CALLBACK_BASE_URL in .env to your tunnel URL (e.g. https://xxx.localhost.run or https://xxx.lhr.life from localhost.run), restart the backend, then refresh this page to see the URL to paste in eBay. Use localhost.run for a stable URL (set once in eBay)."
    return {"callback_url": callback_url, "hint": hint}


@router.get("/ebay/tunnel-check")
async def ebay_tunnel_check(request: Request):
    """
    Reachability check: returns the Host header of this request.
    Call via your tunnel URL (e.g. https://xxx.localhost.run/api/stock/ebay/tunnel-check).
    If the host in the response matches your tunnel URL, the backend is reachable.
    """
    host = request.headers.get("host", "")
    return {
        "ok": True,
        "host": host,
        "message": "If host matches your tunnel URL, the backend is reachable.",
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


def _parse_code_from_query_string(query_string: str) -> Optional[str]:
    """
    Parse 'code' from raw query string. eBay's code can contain # (encoded as %23);
    some proxies/servers truncate at #, so we extract code=... manually until next &.
    """
    if not query_string:
        return None
    for part in query_string.split("&"):
        if part.startswith("code="):
            raw_value = part[5:]  # after "code="
            return unquote(raw_value)
    return None


@router.get("/ebay/callback")
async def ebay_oauth_callback(
    request: Request,
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

    if not code and request.scope.get("query_string"):
        code = _parse_code_from_query_string(request.scope["query_string"].decode("utf-8"))
    if not code:
        # User may have declined consent, opened callback URL directly, or eBay sent them to Auth Declined URL
        redirect_url = f"{base_url}/settings?ebay_error=missing_code&ebay_error_detail={quote('No authorization code in callback. Complete the flow from Settings → Reconnect eBay, sign in on eBay, and click Accept. Do not open the callback URL directly.')}"
        return RedirectResponse(url=redirect_url, status_code=302)

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


@router.post("/import", response_model=ImportResponse)
async def run_import(
    body: ImportRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Run order import: full (last 90 days; eBay filter limit) or incremental (since last import).
    Uses Fulfillment API batch data only (no per-order Finances calls). total_due_seller comes from
    paymentSummary in the batch; for net earnings after ad fees, run the backfill-order-earnings endpoint separately.
    """
    if body.mode not in ("full", "incremental"):
        raise HTTPException(status_code=400, detail="mode must be 'full' or 'incremental'")

    try:
        access_token = await get_ebay_access_token(db)
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
                # Use Fulfillment API data as-is (total_due_seller from batch). Use backfill endpoint to correct earnings with Finances API when needed.
                result = await db.execute(
                    select(Order).where(Order.ebay_order_id == o["ebay_order_id"])
                )
                existing_order = result.scalar_one_or_none()
                def _order_payload(o: dict) -> dict:
                    return {
                        "date": o["date"],
                        "country": o["country"],
                        "last_modified": o["last_modified"],
                        "cancel_status": o.get("cancel_status"),
                        "buyer_username": o.get("buyer_username"),
                        "order_currency": o.get("order_currency"),
                        "price_subtotal": o.get("price_subtotal"),
                        "price_total": o.get("price_total"),
                        "tax_total": o.get("tax_total"),
                        "delivery_cost": o.get("delivery_cost"),
                        "price_discount": o.get("price_discount"),
                        "fee_total": o.get("fee_total"),
                        "total_fee_basis_amount": o.get("total_fee_basis_amount"),
                        "total_marketplace_fee": o.get("total_marketplace_fee"),
                        "total_due_seller": o.get("total_due_seller"),
                        "total_due_seller_currency": o.get("total_due_seller_currency"),
                        "order_payment_status": o.get("order_payment_status"),
                        "sales_record_reference": o.get("sales_record_reference"),
                        "ebay_collect_and_remit_tax": o.get("ebay_collect_and_remit_tax"),
                    }

                if existing_order:
                    payload = _order_payload(o)
                    order_changed = any(
                        getattr(existing_order, k, None) != payload.get(k)
                        for k in payload
                    )
                    if order_changed:
                        for k, v in payload.items():
                            setattr(existing_order, k, v)
                        await db.flush()
                        orders_updated += 1
                    order_id = existing_order.order_id
                    result_li = await db.execute(select(LineItem).where(LineItem.order_id == order_id))
                    existing_items = {(li.ebay_line_item_id): li for li in result_li.scalars().all()}
                else:
                    new_order = Order(ebay_order_id=o["ebay_order_id"], **_order_payload(o))
                    db.add(new_order)
                    await db.flush()
                    orders_added += 1
                    order_id = new_order.order_id
                    existing_items = {}

                for li in o["line_items"]:
                    eid = li["ebay_line_item_id"]
                    line_payload = {
                        "sku": li["sku"],
                        "quantity": li["quantity"],
                        "currency": li.get("currency"),
                        "line_item_cost": li.get("line_item_cost"),
                        "discounted_line_item_cost": li.get("discounted_line_item_cost"),
                        "line_total": li.get("line_total"),
                        "tax_amount": li.get("tax_amount"),
                    }
                    if eid in existing_items:
                        line_changed = any(
                            getattr(existing_items[eid], k, None) != line_payload.get(k)
                            for k in line_payload
                        )
                        if line_changed:
                            for k, v in line_payload.items():
                                setattr(existing_items[eid], k, v)
                            line_items_updated += 1
                    else:
                        db.add(LineItem(
                            order_id=order_id,
                            ebay_line_item_id=eid,
                            **line_payload,
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


class BackfillOrderEarningsResponse(BaseModel):
    orders_updated: int
    orders_skipped: int
    error: Optional[str] = None


@router.post("/orders/backfill-order-earnings", response_model=BackfillOrderEarningsResponse)
async def backfill_order_earnings(
    db: AsyncSession = Depends(get_db),
    limit: int = Query(200, ge=1, le=500, description="Max orders to process per run"),
):
    """
    Correct order earnings using eBay Finances API (net = after ad fees). Run after import when you need
    earnings to match eBay UI. For each order, calls getTransactions by orderId; uses SALE minus fees.
    Falls back to getOrder totalDueSeller if Finances returns nothing (e.g. 403). Processes orders with
    null total_due_seller first, then up to `limit` total. Run multiple times to correct all.
    """
    try:
        access_token = await get_ebay_access_token(db)
    except HTTPException:
        raise
    except Exception as e:
        return BackfillOrderEarningsResponse(orders_updated=0, orders_skipped=0, error=str(e))

    try:
        marketplace_id = getattr(app_settings, "EBAY_MARKETPLACE_ID", None) or "EBAY_GB"
        result = await db.execute(
            select(Order).order_by(Order.total_due_seller.asc().nulls_first()).limit(limit)
        )
        orders = result.scalars().all()
        updated = 0
        skipped = 0
        for o in orders:
            tx_resp = await fetch_transactions_for_order(
                access_token, o.ebay_order_id, marketplace_id
            )
            val, cc = parse_net_order_earnings_from_transactions(tx_resp)
            if val is None:
                raw = await fetch_order_by_id(access_token, o.ebay_order_id)
                if raw:
                    ps = raw.get("paymentSummary") or {}
                    val, cc = _parse_total_due_seller(ps.get("totalDueSeller"))
            if val is not None or cc is not None:
                o.total_due_seller = val
                o.total_due_seller_currency = cc
                updated += 1
            else:
                skipped += 1
            ad_total, ad_cc, ad_breakdown = parse_ad_fees_from_transactions(tx_resp)
            if ad_total is not None or ad_breakdown:
                o.ad_fees_total = ad_total
                o.ad_fees_currency = ad_cc
                o.ad_fees_breakdown = ad_breakdown if ad_breakdown else None
        await db.commit()
        return BackfillOrderEarningsResponse(orders_updated=updated, orders_skipped=skipped)
    except Exception as e:
        await db.rollback()
        logger.exception("Backfill order earnings failed")
        return BackfillOrderEarningsResponse(orders_updated=0, orders_skipped=0, error=str(e))


# === Analytics (SM01) ===

class AnalyticsFilterOptionsResponse(BaseModel):
    countries: List[str]
    skus: List[str]


def _countries_for_analytics(raw: List[str]) -> List[str]:
    """Merge PR and VI into US for analytics; return sorted list with US once."""
    merged = {"US" if c in ("PR", "VI") else c for c in raw if c}
    return sorted(merged)


def _not_canceled():
    """Exclude CANCELED orders from analytics (include NULL for legacy data)."""
    return or_(Order.cancel_status.is_(None), Order.cancel_status != "CANCELED")


@router.get("/analytics/filter-options", response_model=AnalyticsFilterOptionsResponse)
async def get_analytics_filter_options(db: AsyncSession = Depends(get_db)):
    """Return distinct countries and SKUs for analytics filter dropdowns. PR and VI merged into US. Cancelled orders excluded."""
    countries_stmt = (
        select(Order.country)
        .distinct()
        .where(Order.country.isnot(None), _not_canceled())
        .order_by(Order.country)
    )
    countries_result = await db.execute(countries_stmt)
    raw_countries = [row[0] for row in countries_result.all() if row[0]]
    countries = _countries_for_analytics(raw_countries)

    skus_stmt = (
        select(LineItem.sku)
        .distinct()
        .select_from(LineItem)
        .join(Order, Order.order_id == LineItem.order_id)
        .where(LineItem.sku.isnot(None), _not_canceled())
        .order_by(LineItem.sku)
    )
    skus_result = await db.execute(skus_stmt)
    skus = [row[0] for row in skus_result.all() if row[0]]

    return AnalyticsFilterOptionsResponse(countries=countries, skus=skus)


class AnalyticsSummaryPoint(BaseModel):
    period: str
    order_count: int
    units_sold: int


class AnalyticsSummaryResponse(BaseModel):
    series: List[AnalyticsSummaryPoint]
    totals: dict


@router.get("/analytics/summary", response_model=AnalyticsSummaryResponse)
async def get_analytics_summary(
    from_date: date = Query(..., alias="from", description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="End date (YYYY-MM-DD)"),
    group_by: str = Query("day", description="Aggregation: day, week, or month"),
    country: Optional[str] = Query(None, description="Filter by order country (2-letter code)"),
    sku: Optional[str] = Query(None, description="Filter by line item SKU"),
    db: AsyncSession = Depends(get_db),
):
    """Sales analytics: time series of order count and units sold, with optional filters (SM01)."""
    if group_by not in ("day", "week", "month"):
        raise HTTPException(status_code=400, detail="group_by must be day, week, or month")
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be <= to")

    period_expr = func.date_trunc(group_by, Order.date).label("period")
    stmt = (
        select(
            period_expr,
            func.count(func.distinct(Order.order_id)).label("order_count"),
            func.coalesce(func.sum(LineItem.quantity), 0).label("units_sold"),
        )
        .select_from(Order)
        .join(LineItem, Order.order_id == LineItem.order_id)
        .where(Order.date >= from_date, Order.date <= to_date, _not_canceled())
    )
    if country and country.strip():
        cc = country.strip().upper()[:2]
        if cc == "US":
            stmt = stmt.where(Order.country.in_(["US", "PR", "VI"]))
        else:
            stmt = stmt.where(Order.country == cc)
    if sku and sku.strip():
        stmt = stmt.where(LineItem.sku == sku.strip())

    stmt = stmt.group_by(period_expr).order_by(period_expr)
    result = await db.execute(stmt)
    rows = result.all()

    series = []
    total_orders = 0
    total_units = 0
    for row in rows:
        period_val = row.period
        if hasattr(period_val, "date"):
            period_val = period_val.date()
        period_str = period_val.isoformat() if hasattr(period_val, "isoformat") else str(period_val)
        order_count = int(row.order_count)
        units_sold = int(row.units_sold)
        series.append(
            AnalyticsSummaryPoint(period=period_str, order_count=order_count, units_sold=units_sold)
        )
        total_orders += order_count
        total_units += units_sold

    return AnalyticsSummaryResponse(
        series=series,
        totals={"order_count": total_orders, "units_sold": total_units},
    )


def _order_currency_to_gbp_rate(order_currency: Optional[str]) -> float:
    """Rate to multiply order-currency amount by to get GBP."""
    if not order_currency:
        return getattr(app_settings, "USD_TO_GBP_RATE", 0.79)
    cc = (order_currency or "").strip().upper()[:3]
    if cc == "GBP":
        return 1.0
    if cc == "EUR":
        return getattr(app_settings, "EUR_TO_GBP_RATE", 0.86)
    return getattr(app_settings, "USD_TO_GBP_RATE", 0.79)


def _order_profit_gbp(
    total_due_seller: Optional[Decimal],
    price_total: Optional[Decimal],
    tax_total: Optional[Decimal],
    order_currency: Optional[str],
    country: Optional[str],
    line_cost_usd_total: Decimal,
    usd_to_gbp: float,
) -> Optional[Decimal]:
    """
    Profit (GBP) = Total Due Seller (GBP) - (landed+postage in USD converted to GBP)
    - 2% of Price Total in GBP - (if UK: VAT/tax_total in GBP).
    """
    if total_due_seller is None:
        return None
    rate = _order_currency_to_gbp_rate(order_currency)
    price_gbp = (price_total or Decimal(0)) * Decimal(str(rate))
    tax_gbp = (tax_total or Decimal(0)) * Decimal(str(rate))
    cost_gbp = line_cost_usd_total * Decimal(str(usd_to_gbp))
    two_pct = Decimal("0.02") * price_gbp
    is_uk = (country or "").strip().upper()[:2] == "GB"
    vat_gbp = tax_gbp if is_uk else Decimal(0)
    return total_due_seller - cost_gbp - two_pct - vat_gbp


def _profit_after_tax(gross_profit: Decimal) -> Decimal:
    """Apply profit tax (e.g. 30%): displayed profit = gross * (1 - rate). See docs/ANALYTICS_PROFIT_LOGIC.md."""
    rate = getattr(app_settings, "PROFIT_TAX_RATE", 0.30)
    return gross_profit * Decimal(str(1.0 - rate))


class AnalyticsBySkuPoint(BaseModel):
    sku_code: str
    quantity_sold: int
    profit_per_unit: Optional[Decimal] = None
    profit: Decimal


@router.get("/analytics/by-sku", response_model=List[AnalyticsBySkuPoint])
async def get_analytics_by_sku(
    from_date: date = Query(..., alias="from", description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="End date (YYYY-MM-DD)"),
    country: Optional[str] = Query(None, description="Filter by order country (2-letter code)"),
    sku: Optional[str] = Query(None, description="Filter by line item SKU"),
    db: AsyncSession = Depends(get_db),
):
    """Sales by SKU: quantity sold and profit. Profit = Total Due Seller (GBP) - (landed+postage USD->GBP) - 2%% price (GBP) - UK VAT if GB."""
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be <= to")

    stmt = (
        select(Order)
        .options(selectinload(Order.line_items))
        .where(Order.date >= from_date, Order.date <= to_date, _not_canceled())
    )
    if country and country.strip():
        cc = country.strip().upper()[:2]
        if cc == "US":
            stmt = stmt.where(Order.country.in_(["US", "PR", "VI"]))
        else:
            stmt = stmt.where(Order.country == cc)
    result = await db.execute(stmt)
    orders = result.scalars().unique().all()
    sku_codes = set()
    for o in orders:
        for li in o.line_items:
            if li.sku and (not sku or li.sku == sku.strip()):
                sku_codes.add(li.sku)
    if not sku_codes:
        return []
    sku_result = await db.execute(select(SKU).where(SKU.sku_code.in_(sku_codes)))
    sku_map = {s.sku_code: s for s in sku_result.scalars().all()}
    usd_to_gbp = getattr(app_settings, "USD_TO_GBP_RATE", 0.79)

    sku_qty: dict = {}
    sku_profit: dict = {}
    for o in orders:
        price_total = o.price_total or Decimal(0)
        if price_total == 0:
            continue
        line_cost_usd = Decimal(0)
        line_proportions = []
        for li in o.line_items:
            if sku and li.sku != sku.strip():
                continue
            s = sku_map.get(li.sku) if li.sku else None
            landed = (s.landed_cost or Decimal(0)) if s else Decimal(0)
            postage = (s.postage_price or Decimal(0)) if s else Decimal(0)
            qty = li.quantity or 0
            line_cost_usd += (landed + postage) * qty
            line_total = li.line_total or Decimal(0)
            line_proportions.append((li.sku or "", qty, line_total / price_total))
        if sku and not line_proportions:
            continue
        order_profit = _order_profit_gbp(
            o.total_due_seller,
            o.price_total,
            o.tax_total,
            o.order_currency,
            o.country,
            line_cost_usd,
            usd_to_gbp,
        )
        if order_profit is None:
            continue
        net_profit = _profit_after_tax(order_profit)
        for sku_code, qty, prop in line_proportions:
            sku_qty[sku_code] = sku_qty.get(sku_code, 0) + qty
            sku_profit[sku_code] = sku_profit.get(sku_code, Decimal(0)) + net_profit * prop

    out = []
    for sku_code in sorted(sku_profit.keys(), key=lambda x: (-sku_qty.get(x, 0), x)):
        qty = sku_qty.get(sku_code, 0)
        profit = sku_profit.get(sku_code, Decimal(0))
        out.append(
            AnalyticsBySkuPoint(
                sku_code=sku_code,
                quantity_sold=qty,
                profit_per_unit=None,
                profit=profit,
            )
        )
    return out


class AnalyticsByCountryPoint(BaseModel):
    country: str
    quantity_sold: int
    profit: Decimal


def _country_group(country: Optional[str]) -> str:
    if not country:
        return "Unknown"
    cc = country.strip().upper()[:2]
    if cc in ("PR", "VI"):
        return "US"
    return cc


@router.get("/analytics/by-country", response_model=List[AnalyticsByCountryPoint])
async def get_analytics_by_country(
    from_date: date = Query(..., alias="from", description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="End date (YYYY-MM-DD)"),
    sku: Optional[str] = Query(None, description="Filter by line item SKU"),
    db: AsyncSession = Depends(get_db),
):
    """Sales by country: quantity sold and profit. Profit = Total Due Seller (GBP) - costs - 2%% price - UK VAT if GB. PR/VI merged into US."""
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be <= to")

    stmt = (
        select(Order)
        .options(selectinload(Order.line_items))
        .where(Order.date >= from_date, Order.date <= to_date, _not_canceled())
    )
    result = await db.execute(stmt)
    orders = result.scalars().unique().all()
    if sku and sku.strip():
        orders = [o for o in orders if any(li.sku == sku.strip() for li in o.line_items)]
    sku_codes = set()
    for o in orders:
        for li in o.line_items:
            if li.sku:
                sku_codes.add(li.sku)
    sku_map = {}
    if sku_codes:
        sku_result = await db.execute(select(SKU).where(SKU.sku_code.in_(sku_codes)))
        sku_map = {s.sku_code: s for s in sku_result.scalars().all()}
    usd_to_gbp = getattr(app_settings, "USD_TO_GBP_RATE", 0.79)

    country_qty = {}
    country_profit = {}
    for o in orders:
        line_cost_usd = Decimal(0)
        qty_for_country = 0
        for li in o.line_items:
            if sku and li.sku != sku.strip():
                continue
            s = sku_map.get(li.sku) if li.sku else None
            landed = (s.landed_cost or Decimal(0)) if s else Decimal(0)
            postage = (s.postage_price or Decimal(0)) if s else Decimal(0)
            qty = li.quantity or 0
            line_cost_usd += (landed + postage) * qty
            qty_for_country += qty
        order_profit = _order_profit_gbp(
            o.total_due_seller,
            o.price_total,
            o.tax_total,
            o.order_currency,
            o.country,
            line_cost_usd,
            usd_to_gbp,
        )
        if order_profit is None:
            continue
        net_profit = _profit_after_tax(order_profit)
        cg = _country_group(o.country)
        country_qty[cg] = country_qty.get(cg, 0) + qty_for_country
        country_profit[cg] = country_profit.get(cg, Decimal(0)) + net_profit

    out = [
        AnalyticsByCountryPoint(
            country=cg,
            quantity_sold=country_qty.get(cg, 0),
            profit=country_profit.get(cg, Decimal(0)),
        )
        for cg in sorted(country_profit.keys(), key=lambda x: (-country_qty.get(x, 0), x))
    ]
    return out


# === Debug: raw eBay order (paymentSummary / Order earnings) ===

@router.get("/orders/{ebay_order_id}/ebay-raw")
async def get_order_ebay_raw(
    ebay_order_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Fetch one order from eBay via getOrder and return paymentSummary and pricingSummary.
    Use to verify what eBay returns for Order earnings (totalDueSeller).
    Example: GET /api/stock/orders/11-14176-11233/ebay-raw
    """
    try:
        access_token = await get_ebay_access_token(db)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    raw = await fetch_order_by_id(access_token, ebay_order_id)
    if not raw:
        raise HTTPException(status_code=404, detail="Order not found on eBay")
    return {
        "orderId": raw.get("orderId"),
        "paymentSummary": raw.get("paymentSummary"),
        "pricingSummary": raw.get("pricingSummary"),
    }


# === Last orders (all Fulfillment API fields we store) ===

class LineItemRow(BaseModel):
    id: int
    ebay_line_item_id: str
    sku: str
    quantity: int
    currency: Optional[str] = None
    line_item_cost: Optional[Decimal] = None
    discounted_line_item_cost: Optional[Decimal] = None
    line_total: Optional[Decimal] = None
    tax_amount: Optional[Decimal] = None


class OrderWithLinesResponse(BaseModel):
    order_id: int
    ebay_order_id: str
    date: date
    country: str
    last_modified: datetime
    cancel_status: Optional[str] = None
    buyer_username: Optional[str] = None
    order_currency: Optional[str] = None
    price_subtotal: Optional[Decimal] = None
    price_total: Optional[Decimal] = None
    tax_total: Optional[Decimal] = None
    delivery_cost: Optional[Decimal] = None
    price_discount: Optional[Decimal] = None
    fee_total: Optional[Decimal] = None
    total_fee_basis_amount: Optional[Decimal] = None
    total_marketplace_fee: Optional[Decimal] = None
    total_due_seller: Optional[Decimal] = None
    total_due_seller_currency: Optional[str] = None
    ad_fees_total: Optional[Decimal] = None
    ad_fees_currency: Optional[str] = None
    ad_fees_breakdown: Optional[List[dict]] = None
    order_payment_status: Optional[str] = None
    sales_record_reference: Optional[str] = None
    ebay_collect_and_remit_tax: Optional[bool] = None
    line_items: List[LineItemRow]


@router.get("/orders/latest", response_model=List[OrderWithLinesResponse])
async def get_latest_orders(
    limit: int = Query(10, ge=1, le=100, description="Number of orders to return"),
    db: AsyncSession = Depends(get_db),
):
    """Last N orders with all Fulfillment API fields we store (pricing, tax, fees)."""
    result = await db.execute(
        select(Order)
        .options(selectinload(Order.line_items))
        .order_by(Order.last_modified.desc())
        .limit(limit)
    )
    orders = result.scalars().all()
    return [
        OrderWithLinesResponse(
            order_id=o.order_id,
            ebay_order_id=o.ebay_order_id,
            date=o.date,
            country=o.country,
            last_modified=o.last_modified,
            cancel_status=o.cancel_status,
            buyer_username=o.buyer_username,
            order_currency=o.order_currency,
            price_subtotal=o.price_subtotal,
            price_total=o.price_total,
            tax_total=o.tax_total,
            delivery_cost=o.delivery_cost,
            price_discount=o.price_discount,
            fee_total=o.fee_total,
            total_fee_basis_amount=o.total_fee_basis_amount,
            total_marketplace_fee=o.total_marketplace_fee,
            total_due_seller=o.total_due_seller,
            total_due_seller_currency=o.total_due_seller_currency,
            ad_fees_total=o.ad_fees_total,
            ad_fees_currency=o.ad_fees_currency,
            ad_fees_breakdown=o.ad_fees_breakdown,
            order_payment_status=o.order_payment_status,
            sales_record_reference=o.sales_record_reference,
            ebay_collect_and_remit_tax=o.ebay_collect_and_remit_tax,
            line_items=[
                LineItemRow(
                    id=li.id,
                    ebay_line_item_id=li.ebay_line_item_id,
                    sku=li.sku,
                    quantity=li.quantity,
                    currency=li.currency,
                    line_item_cost=li.line_item_cost,
                    discounted_line_item_cost=li.discounted_line_item_cost,
                    line_total=li.line_total,
                    tax_amount=li.tax_amount,
                )
                for li in o.line_items
            ],
        )
        for o in orders
    ]


# === Stock Planning (SM04) ===

class VelocityResponse(BaseModel):
    sku: str
    units_sold: int
    days: int
    units_per_day: float


@router.get("/planning/velocity", response_model=VelocityResponse)
async def get_sales_velocity(
    sku: str = Query(..., description="SKU code"),
    from_date: date = Query(..., alias="from"),
    to_date: date = Query(..., alias="to"),
    db: AsyncSession = Depends(get_db),
):
    """Sales velocity for a SKU over a date range (units per day). Used for stock planning (SM04)."""
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be <= to")
    days = (to_date - from_date).days + 1
    if days <= 0:
        raise HTTPException(status_code=400, detail="Invalid date range")

    stmt = (
        select(func.coalesce(func.sum(LineItem.quantity), 0).label("units"))
        .select_from(LineItem)
        .join(Order, Order.order_id == LineItem.order_id)
        .where(
            LineItem.sku == sku.strip(),
            Order.date >= from_date,
            Order.date <= to_date,
            _not_canceled(),
        )
    )
    result = await db.execute(stmt)
    units_sold = int(result.scalar_one())
    return VelocityResponse(
        sku=sku.strip(),
        units_sold=units_sold,
        days=days,
        units_per_day=round(units_sold / days, 2) if days else 0,
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


# === Purchase Orders (SM06-SM07) ===

class POLineItemCreate(BaseModel):
    sku_code: str = Field(..., max_length=100)
    quantity: int = Field(..., ge=1)


class POCreate(BaseModel):
    order_date: date
    order_value: Decimal = Field(..., ge=0)
    lead_time_days: int = Field(default=90, ge=0)
    status: str = Field(default="In Progress", max_length=20)
    line_items: List[POLineItemCreate] = Field(..., min_length=1)


class POLineItemResponse(BaseModel):
    id: int
    sku_code: str
    quantity: int

    model_config = {"from_attributes": True}


class POResponse(BaseModel):
    id: int
    status: str
    order_date: date
    order_value: Decimal
    lead_time_days: int
    actual_delivery_date: Optional[date]
    line_items: List[POLineItemResponse]

    model_config = {"from_attributes": True}


@router.get("/purchase-orders", response_model=List[POResponse])
async def list_purchase_orders(
    status_filter: Optional[str] = Query(None, alias="status", description="Filter by status"),
    db: AsyncSession = Depends(get_db),
):
    """List purchase orders (SM06-SM07)."""
    q = (
        select(PurchaseOrder)
        .options(selectinload(PurchaseOrder.line_items))
        .order_by(PurchaseOrder.order_date.desc())
    )
    if status_filter and status_filter.strip():
        q = q.where(PurchaseOrder.status == status_filter.strip())
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/purchase-orders", response_model=POResponse, status_code=status.HTTP_201_CREATED)
async def create_purchase_order(body: POCreate, db: AsyncSession = Depends(get_db)):
    """Create a purchase order with line items."""
    for li in body.line_items:
        r = await db.execute(select(SKU).where(SKU.sku_code == li.sku_code))
        if not r.scalar_one_or_none():
            raise HTTPException(status_code=400, detail=f"SKU not found: {li.sku_code}")

    po = PurchaseOrder(
        order_date=body.order_date,
        order_value=body.order_value,
        lead_time_days=body.lead_time_days,
        status=body.status.strip() or "In Progress",
    )
    db.add(po)
    await db.flush()
    for li in body.line_items:
        pol = POLineItem(po_id=po.id, sku_code=li.sku_code, quantity=li.quantity)
        db.add(pol)
    await db.commit()
    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == po.id).options(selectinload(PurchaseOrder.line_items))
    )
    return result.scalar_one()


@router.get("/purchase-orders/{po_id}", response_model=POResponse)
async def get_purchase_order(po_id: int, db: AsyncSession = Depends(get_db)):
    """Get one purchase order."""
    result = await db.execute(
        select(PurchaseOrder)
        .where(PurchaseOrder.id == po_id)
        .options(selectinload(PurchaseOrder.line_items))
    )
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    return po


@router.put("/purchase-orders/{po_id}", response_model=POResponse)
async def update_purchase_order(
    po_id: int,
    status: Optional[str] = Query(None),
    actual_delivery_date: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Update purchase order status and/or actual delivery date."""
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    if status is not None and status.strip():
        po.status = status.strip()
    if actual_delivery_date is not None:
        po.actual_delivery_date = actual_delivery_date
    await db.commit()
    result = await db.execute(
        select(PurchaseOrder).where(PurchaseOrder.id == po_id).options(selectinload(PurchaseOrder.line_items))
    )
    return result.scalar_one()


@router.delete("/purchase-orders/{po_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_purchase_order(po_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a purchase order and its line items."""
    result = await db.execute(select(PurchaseOrder).where(PurchaseOrder.id == po_id))
    po = result.scalar_one_or_none()
    if not po:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    await db.delete(po)
    await db.commit()


# === Supplier Order Message (SM06) ===

class OrderLineItem(BaseModel):
    sku_code: str
    title: str
    quantity: int


class GenerateOrderMessageRequest(BaseModel):
    items: List[OrderLineItem] = Field(..., min_length=1)


class GenerateOrderMessageResponse(BaseModel):
    message: str
    total_units: int
    countries: List[str]


@router.post("/generate-order-message", response_model=GenerateOrderMessageResponse)
async def generate_order_message(
    body: GenerateOrderMessageRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Generate a supplier order message (SM06).
    Groups items by country code (first 2 letters of SKU), includes warehouse addresses.
    """
    from collections import defaultdict
    
    # Group items by country code (first 2 letters of SKU)
    by_country: dict[str, list[OrderLineItem]] = defaultdict(list)
    for item in body.items:
        country_code = item.sku_code[:2].upper() if len(item.sku_code) >= 2 else "XX"
        by_country[country_code].append(item)
    
    # Fetch warehouses
    warehouse_result = await db.execute(select(Warehouse))
    warehouses = {w.country_code.upper(): w for w in warehouse_result.scalars().all()}
    
    # Build message
    lines = []
    total_units = 0
    countries_list = sorted(by_country.keys())
    
    for country in countries_list:
        items = sorted(by_country[country], key=lambda x: x.sku_code)
        lines.append(f"=== {country} ===")
        lines.append("")
        for item in items:
            lines.append(f"{item.sku_code}\t{item.title}\t{item.quantity}")
            total_units += item.quantity
        lines.append("")
        
        # Add warehouse address if available
        warehouse = warehouses.get(country)
        if warehouse:
            lines.append(f"Ship to: {warehouse.shortname}")
            lines.append(warehouse.address)
        else:
            lines.append(f"Ship to: [No warehouse configured for {country}]")
        lines.append("")
        lines.append("")
    
    # Summary
    lines.append("---")
    lines.append(f"Total: {total_units} units across {len(countries_list)} countries")
    
    return GenerateOrderMessageResponse(
        message="\n".join(lines),
        total_units=total_units,
        countries=countries_list,
    )
