"""
Stock run-out forecast: average eBay sales over in-stock days (AVL >= 7) in the selected period.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone, time as dt_time
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import OCStockMovementLine, OCSkuInventory, OCSkuMapping
from app.models.stock import LineItem, Order

MIN_AVL_IN_STOCK = 7
REORDER_LEAD_TIME_DAYS = 90  # supplier delivery ~3 months after order
NOTE_SUFFIX = "Assumes no inbound restock."


def average_burn_rate(daily_sales: List[float]) -> float:
    """Simple mean units/day over the in-stock sample days."""
    if not daily_sales:
        return 0.0
    return sum(float(s) for s in daily_sales) / len(daily_sales)


def forecast_note(window_start: date, window_end: date) -> str:
    return (
        f"Burn rate = average eBay units/day over in-stock days (AVL >= {MIN_AVL_IN_STOCK}) "
        f"from {window_start.isoformat()} to {window_end.isoformat()}. "
        f"Ordered = available + in transit + received (OC snapshot); ordered run-out = ordered ÷ burn rate; "
        f"reorder = order {REORDER_LEAD_TIME_DAYS} days before run-out (qty ≈ burn × {REORDER_LEAD_TIME_DAYS} days). {NOTE_SUFFIX}"
    )


def forward_fill_daily_avl(
    points: List[Tuple[datetime, int]],
    start: date,
    end: date,
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
        last_avl = 0
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


def _cover_and_oos(total: int, burn: float, today: date) -> Tuple[Optional[float], Optional[str]]:
    if burn <= 0 or total < 0:
        return None, None
    doc = total / burn
    oos = (today + timedelta(days=int(math.ceil(doc)))).isoformat()
    return round(doc, 4), oos


def _reorder_plan(
    oos_iso: Optional[str],
    burn: float,
    today: date,
    lead_days: int = REORDER_LEAD_TIME_DAYS,
) -> Tuple[Optional[int], Optional[str], Optional[float]]:
    """
    JIT reorder: place order lead_days before run-out; qty covers sales over the lead window.
    Returns (quantity, reorder_by_date ISO, days_until_reorder from today).
    """
    if not oos_iso or burn <= 0:
        return None, None, None
    oos_d = date.fromisoformat(oos_iso)
    reorder_d = oos_d - timedelta(days=lead_days)
    qty = int(math.ceil(burn * lead_days))
    days_until = float((reorder_d - today).days)
    return qty, reorder_d.isoformat(), days_until


def _forecast_row(
    *,
    seller_skuid: str,
    mfskuid: str,
    sku_name: str,
    current_available: int = 0,
    current_in_transit: int = 0,
    current_received: int = 0,
    ordered_total: int = 0,
    burn_rate_per_day: Optional[float] = None,
    in_stock_days_used: int = 0,
    ordered_days_of_cover: Optional[float] = None,
    ordered_estimated_oos_date: Optional[str] = None,
    reorder_quantity: Optional[int] = None,
    reorder_by_date: Optional[str] = None,
    days_until_reorder: Optional[float] = None,
    total_sales_in_window: Optional[int] = None,
) -> dict:
    return {
        "seller_skuid": seller_skuid,
        "mfskuid": mfskuid,
        "sku_name": sku_name,
        "current_available": current_available,
        "current_in_transit": current_in_transit,
        "current_received": current_received,
        "ordered_total": ordered_total,
        "burn_rate_per_day": burn_rate_per_day,
        "in_stock_days_used": in_stock_days_used,
        "ordered_days_of_cover": ordered_days_of_cover,
        "ordered_estimated_oos_date": ordered_estimated_oos_date,
        "reorder_quantity": reorder_quantity,
        "reorder_by_date": reorder_by_date,
        "days_until_reorder": days_until_reorder,
        "total_sales_in_window": total_sales_in_window,
    }


async def _latest_avl_actual_count(
    db: AsyncSession,
    connection_id: int,
    mfskuid: str,
    service_region: Optional[str],
) -> Optional[int]:
    mov = OCStockMovementLine
    event_t = func.coalesce(mov.update_time_utc, mov.created_at)
    filters = [
        mov.connection_id == connection_id,
        func.lower(mov.mfskuid) == mfskuid.strip().lower(),
        func.upper(mov.inventory_status) == "AVL",
    ]
    if service_region is not None and str(service_region).strip():
        filters.append(mov.service_region == str(service_region).strip())
    stmt = (
        select(mov.actual_count)
        .where(*filters)
        .order_by(event_t.desc())
        .limit(1)
    )
    r = await db.execute(stmt)
    row = r.first()
    if row is None or row[0] is None:
        return None
    return int(row[0])


async def _latest_pipeline_counts(
    db: AsyncSession,
    connection_id: int,
    mfskuid: str,
    service_region: Optional[str],
) -> Tuple[int, int]:
    """In-transit and received quantities from the latest OC StockSnapshot pull."""
    filters = [
        OCSkuInventory.connection_id == connection_id,
        func.lower(OCSkuInventory.mfskuid) == mfskuid.strip().lower(),
    ]
    if service_region is not None and str(service_region).strip():
        filters.append(OCSkuInventory.service_region == str(service_region).strip())
    stmt = select(OCSkuInventory.in_transit, OCSkuInventory.received).where(*filters).limit(1)
    r = await db.execute(stmt)
    row = r.first()
    if row is None:
        return 0, 0
    in_transit = max(0, int(row[0] or 0))
    received = max(0, int(row[1] or 0))
    return in_transit, received


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
            or_(Order.cancel_status.is_(None), Order.cancel_status != "CANCELED"),
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
    window_start: date,
    window_end: date,
) -> dict:
    from app.api.inventory_status import list_inventory_history

    seller_skuid = (mapping.seller_skuid or "").strip()
    mfskuid = (mapping.mfskuid or "").strip()
    sku_name = (mapping.sku_code or "").strip() or seller_skuid
    region_filter = (mapping.service_region or "").strip() or None

    if not mfskuid or not seller_skuid:
        return _forecast_row(seller_skuid=seller_skuid, mfskuid=mfskuid, sku_name=sku_name)

    today = date.today()
    latest_avl = await _latest_avl_actual_count(db, connection_id, mfskuid, region_filter)
    current_avl = max(0, latest_avl) if latest_avl is not None else 0
    current_in_transit, current_received = await _latest_pipeline_counts(
        db, connection_id, mfskuid, region_filter
    )
    ordered_total = current_avl + current_in_transit + current_received

    stock_fields = dict(
        seller_skuid=seller_skuid,
        mfskuid=mfskuid,
        sku_name=sku_name,
        current_available=current_avl,
        current_in_transit=current_in_transit,
        current_received=current_received,
        ordered_total=ordered_total,
    )

    hist = await list_inventory_history(
        db=db,
        from_date=window_start - timedelta(days=120),
        to_date=window_end,
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

    daily = forward_fill_daily_avl(raw_pts, window_start, window_end)
    in_stock_days = [
        d for d in _daterange(window_start, window_end) if daily.get(d, 0) >= MIN_AVL_IN_STOCK
    ]

    line_skus = await _line_item_skus_for_mapping(db, connection_id, seller_skuid)
    sales_by_date = await _ebay_units_by_order_date(db, line_skus, window_start, window_end)
    total_sales_in_window = int(sum(sales_by_date.values()))
    daily_sales = [float(sales_by_date.get(d, 0)) for d in in_stock_days]
    burn = average_burn_rate(daily_sales)

    if burn <= 0:
        return _forecast_row(
            **stock_fields,
            in_stock_days_used=len(in_stock_days),
            total_sales_in_window=total_sales_in_window,
        )

    ordered_doc, ordered_oos = _cover_and_oos(ordered_total, burn, today)
    reorder_qty, reorder_by, days_until_reorder = _reorder_plan(ordered_oos, burn, today)
    return _forecast_row(
        **stock_fields,
        burn_rate_per_day=round(burn, 4),
        in_stock_days_used=len(in_stock_days),
        ordered_days_of_cover=ordered_doc,
        ordered_estimated_oos_date=ordered_oos,
        reorder_quantity=reorder_qty,
        reorder_by_date=reorder_by,
        days_until_reorder=days_until_reorder,
        total_sales_in_window=total_sales_in_window,
    )


async def build_stock_forecast_payload(
    db: AsyncSession,
    connection_id: int,
    window_start: date,
    window_end: date,
) -> dict:
    mr = await db.execute(
        select(OCSkuMapping)
        .where(OCSkuMapping.connection_id == connection_id)
        .order_by(OCSkuMapping.seller_skuid.asc(), OCSkuMapping.mfskuid.asc())
    )
    mappings = list(mr.scalars().all())
    rows = [
        await _forecast_for_mapping_row(db, connection_id, m, window_start, window_end)
        for m in mappings
    ]

    rows.sort(
        key=lambda x: (
            1 if x.get("ordered_days_of_cover") is None else 0,
            float(x["ordered_days_of_cover"]) if x.get("ordered_days_of_cover") is not None else float("inf"),
        )
    )

    now = datetime.now(timezone.utc)
    return {
        "forecasts": rows,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "note": forecast_note(window_start, window_end),
        "from_date": window_start.isoformat(),
        "to_date": window_end.isoformat(),
    }
