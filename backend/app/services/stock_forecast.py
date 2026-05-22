"""
Stock run-out forecast: linearly weighted eBay sales over the last 90 in-stock days (AVL >= 5).
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone, time as dt_time
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import OCStockMovementLine, OCSkuMapping
from app.models.stock import LineItem, Order

MIN_AVL_IN_STOCK = 5
LOOKBACK_DAYS = 183  # ~6 months
IN_STOCK_SAMPLE_CAP = 90
MIN_IN_STOCK_FOR_CONFIDENCE = 7
NOTE_TEXT = (
    "Burn rate = linearly weighted avg of eBay sales over last 90 in-stock days (AVL >= 5). "
    "Assumes no inbound restock."
)


def weighted_burn_rate(daily_sales: List[float]) -> float:
    """
    daily_sales[0] = oldest in-stock day, daily_sales[-1] = most recent.
    Linear weights: oldest gets 1, most recent gets len(daily_sales).
    """
    n = len(daily_sales)
    if n == 0:
        return 0.0
    weight_sum = 0.0
    value_sum = 0.0
    for i, sales in enumerate(daily_sales):
        w = float(i + 1)
        value_sum += float(sales) * w
        weight_sum += w
    return value_sum / weight_sum if weight_sum > 0 else 0.0


def forward_fill_daily_avl(
    points: List[Tuple[datetime, int]],
    start: date,
    end: date,
    initial_avl: int = 0,
) -> Dict[date, int]:
    """Last AVL total on or before end of each calendar day (matches chart forward-fill)."""
    if start > end:
        return {}
    sorted_pts = sorted(points, key=lambda x: x[0])
    out: Dict[date, int] = {}
    cur = start
    while cur <= end:
        day_end = datetime.combine(cur, dt_time(23, 59, 59, 999999))
        if day_end.tzinfo is not None:
            day_end = day_end.replace(tzinfo=None)
        lim = day_end
        last_avl = initial_avl
        for ts, avl in sorted_pts:
            if ts <= lim:
                last_avl = avl
        out[cur] = last_avl
        cur = cur + timedelta(days=1)
    return out


def _daterange(a: date, b: date) -> List[date]:
    out: List[date] = []
    cur = a
    while cur <= b:
        out.append(cur)
        cur = cur + timedelta(days=1)
    return out


async def _latest_avl_actual_count(
    db: AsyncSession,
    connection_id: int,
    mfskuid: str,
    service_region: Optional[str],
) -> Optional[int]:
    mov = OCStockMovementLine
    event_t = func.coalesce(mov.update_time_utc, mov.created_at)
    ac = func.coalesce(mov.actual_count, 0)
    filters = [
        mov.connection_id == connection_id,
        func.lower(mov.mfskuid) == mfskuid.strip().lower(),
        func.upper(mov.inventory_status) == "AVL",
    ]
    if service_region is not None and str(service_region).strip():
        filters.append(mov.service_region == str(service_region).strip())

    if service_region is None or not str(service_region).strip():
        region_expr = func.lower(mov.service_region)
        per_burst = (
            select(
                event_t.label("ts"),
                region_expr.label("service_region"),
                func.max(ac).label("avl_after"),
            )
            .where(*filters)
            .group_by(event_t, region_expr)
        ).subquery()
        rn = func.row_number().over(
            partition_by=per_burst.c.service_region,
            order_by=per_burst.c.ts.desc(),
        ).label("rn")
        latest_by_region = select(per_burst.c.avl_after, rn).subquery()
        stmt = select(func.sum(latest_by_region.c.avl_after)).where(latest_by_region.c.rn == 1)
        r = await db.execute(stmt)
        total = r.scalar()
        return int(total) if total is not None else None

    per_burst = (
        select(
            event_t.label("ts"),
            func.max(ac).label("avl_after"),
        )
        .where(*filters)
        .group_by(event_t)
    ).subquery()
    stmt = (
        select(per_burst.c.avl_after)
        .order_by(per_burst.c.ts.desc())
        .limit(1)
    )
    r = await db.execute(stmt)
    row = r.first()
    if row is None or row[0] is None:
        return None
    return int(row[0])


async def _line_item_skus_for_mapping(
    db: AsyncSession,
    connection_id: int,
    seller_skuid: str,
) -> List[str]:
    mr = await db.execute(
        select(OCSkuMapping.sku_code, OCSkuMapping.seller_skuid).where(
            OCSkuMapping.connection_id == connection_id,
            func.lower(OCSkuMapping.seller_skuid) == seller_skuid.strip().lower(),
        )
    )
    keys: set[str] = set()
    for row in mr.all():
        sc = (row.sku_code or "").strip()
        ss = (row.seller_skuid or "").strip()
        if sc:
            keys.add(sc)
        if ss:
            keys.add(ss)
    return sorted(keys)


async def _ebay_units_by_order_date(
    db: AsyncSession,
    line_item_skus: List[str],
    window_start: date,
    window_end: date,
) -> Dict[date, int]:
    if not line_item_skus:
        return {}
    stmt = (
        select(Order.date, func.coalesce(func.sum(LineItem.quantity), 0))
        .select_from(LineItem)
        .join(Order, Order.order_id == LineItem.order_id)
        .where(
            LineItem.sku.in_(line_item_skus),
            Order.cancel_status != "CANCELED",
            Order.date >= window_start,
            Order.date <= window_end,
        )
        .group_by(Order.date)
    )
    r = await db.execute(stmt)
    return {row[0]: int(row[1] or 0) for row in r.all()}


async def _forecast_for_mapping_row(
    db: AsyncSession,
    connection_id: int,
    mapping: OCSkuMapping,
) -> dict:
    from app.api.inventory_status import list_inventory_history

    seller_skuid = (mapping.seller_skuid or "").strip()
    mfskuid = (mapping.mfskuid or "").strip()
    sku_name = (mapping.sku_code or "").strip() or seller_skuid
    region_raw = mapping.service_region
    service_region = (region_raw or "").strip() or "—"

    base = {
        "seller_skuid": seller_skuid,
        "mfskuid": mfskuid,
        "sku_name": sku_name,
        "service_region": service_region,
    }

    if not mfskuid or not seller_skuid:
        return {
            **base,
            "current_available": 0,
            "burn_rate_per_day": None,
            "in_stock_days_used": 0,
            "days_of_cover": None,
            "estimated_oos_date": None,
            "confidence": "insufficient_data",
            "total_sales_in_window": None,
        }

    region_filter = (region_raw or "").strip() or None

    latest = await _latest_avl_actual_count(db, connection_id, mfskuid, region_filter)
    if latest is None or latest <= 0:
        return {
            **base,
            "current_available": 0 if latest is None else max(0, latest),
            "burn_rate_per_day": None,
            "in_stock_days_used": 0,
            "days_of_cover": None,
            "estimated_oos_date": None,
            "confidence": "already_oos",
            "total_sales_in_window": None,
        }

    current_avl = latest
    today = date.today()
    window_start = today - timedelta(days=LOOKBACK_DAYS)
    ext_from = window_start - timedelta(days=120)

    hist = await list_inventory_history(
        db=db,
        from_date=ext_from,
        to_date=today,
        seller_skuid=None,
        sku_code=None,
        mfskuid=mfskuid,
        service_region=region_filter,
    )
    raw_pts: List[Tuple[datetime, int]] = []
    for p in hist.points:
        ts = p.recorded_at
        if ts.tzinfo is not None:
            ts = ts.replace(tzinfo=None)
        raw_pts.append((ts, int(p.available or 0)))

    daily = forward_fill_daily_avl(raw_pts, window_start, today, initial_avl=int(hist.opening_available or 0))
    in_stock_days_ordered = [d for d in _daterange(window_start, today) if daily.get(d, 0) >= MIN_AVL_IN_STOCK]
    newest_90 = in_stock_days_ordered[-IN_STOCK_SAMPLE_CAP:]
    n = len(newest_90)

    line_skus = await _line_item_skus_for_mapping(db, connection_id, seller_skuid)
    sales_by_date = await _ebay_units_by_order_date(db, line_skus, window_start, today)
    total_sales_in_window = int(sum(sales_by_date.values()))

    daily_sales = [float(sales_by_date.get(d, 0)) for d in newest_90]
    burn = weighted_burn_rate(daily_sales)
    in_stock_days_used = n

    if burn <= 0:
        return {
            **base,
            "current_available": current_avl,
            "burn_rate_per_day": None,
            "in_stock_days_used": in_stock_days_used,
            "days_of_cover": None,
            "estimated_oos_date": None,
            "confidence": "no_sales",
            "total_sales_in_window": total_sales_in_window,
        }

    doc = current_avl / burn
    oos_dt = today + timedelta(days=int(math.ceil(doc)))
    oos = oos_dt.isoformat()

    if in_stock_days_used < MIN_IN_STOCK_FOR_CONFIDENCE:
        confidence = "insufficient_data"
    elif in_stock_days_used < 30:
        confidence = "low"
    else:
        confidence = "normal"

    return {
        **base,
        "current_available": current_avl,
        "burn_rate_per_day": round(burn, 4),
        "in_stock_days_used": in_stock_days_used,
        "days_of_cover": round(doc, 4),
        "estimated_oos_date": oos,
        "confidence": confidence,
        "total_sales_in_window": total_sales_in_window,
    }


async def build_stock_forecast_payload(db: AsyncSession, connection_id: int) -> dict:
    mr = await db.execute(
        select(OCSkuMapping)
        .where(OCSkuMapping.connection_id == connection_id)
        .order_by(OCSkuMapping.seller_skuid.asc(), OCSkuMapping.mfskuid.asc())
    )
    mappings = list(mr.scalars().all())
    rows: List[dict] = []
    for m in mappings:
        rows.append(await _forecast_for_mapping_row(db, connection_id, m))

    def sort_key(x: dict) -> Tuple[int, float]:
        doc = x.get("days_of_cover")
        if doc is None:
            return (1, float("inf"))
        return (0, float(doc))

    rows.sort(key=sort_key)

    now = datetime.now(timezone.utc)
    generated_at = now.isoformat().replace("+00:00", "Z")
    return {
        "forecasts": rows,
        "generated_at": generated_at,
        "note": NOTE_TEXT,
    }
