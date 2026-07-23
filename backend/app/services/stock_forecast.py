"""
Stock run-out forecast: average eBay sales over in-stock days (AVL >= 7) in the selected period.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone, time as dt_time
from typing import Dict, List, Optional, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.settings import OCStockMovementLine, OCSkuInventory, OCSkuMapping
from app.models.stock import LineItem, Order, SKU
from app.utils.date_ranges import complete_days_range

MIN_AVL_IN_STOCK = 7
# Default when settings unavailable (tests); production uses STOCK_REORDER_* from config.
REORDER_LEAD_TIME_DAYS = 90
NOTE_SUFFIX = "Assumes no inbound restock."


def effective_reorder_lead_days() -> int:
    lead = int(getattr(app_settings, "STOCK_REORDER_LEAD_TIME_DAYS", REORDER_LEAD_TIME_DAYS))
    buf = int(getattr(app_settings, "STOCK_REORDER_BUFFER_DAYS", 0))
    return max(0, lead) + max(0, buf)


def average_burn_rate(daily_sales: List[float]) -> float:
    """Simple mean units/day over the in-stock sample days."""
    if not daily_sales:
        return 0.0
    return sum(float(s) for s in daily_sales) / len(daily_sales)


def forecast_note(window_start: date, window_end: date) -> str:
    lead = effective_reorder_lead_days()
    return (
        f"Burn rate = average eBay units/day over in-stock days (AVL >= {MIN_AVL_IN_STOCK}) "
        f"from {window_start.isoformat()} to {window_end.isoformat()}. "
        f"Ordered = available + in transit + received (OC snapshot); ordered run-out = ordered ÷ burn rate; "
        f"reorder = order {lead} days before run-out (qty ≈ burn × {lead} days). {NOTE_SUFFIX}"
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
    if burn <= 0 or total <= 0:
        return None, None
    doc = total / burn
    oos = (today + timedelta(days=int(math.ceil(doc)))).isoformat()
    return round(doc, 4), oos


def reorder_cost_gbp(
    reorder_qty: Optional[int],
    landed_cost_usd: Optional[float],
    usd_to_gbp: float,
) -> Optional[float]:
    """Reorder line cost in GBP from SKU landed cost (USD) × qty × USD→GBP rate."""
    if reorder_qty is None or reorder_qty <= 0:
        return None
    unit = float(landed_cost_usd or 0)
    if unit <= 0:
        return None
    return round(reorder_qty * unit * usd_to_gbp, 2)


def _reorder_plan(
    oos_iso: Optional[str],
    burn: float,
    today: date,
    lead_days: Optional[int] = None,
) -> Tuple[Optional[int], Optional[str], Optional[float]]:
    """
    JIT reorder: place order lead_days before run-out; qty covers sales over the lead window.
    Returns (quantity, reorder_by_date ISO, days_until_reorder from today).
    """
    if not oos_iso or burn <= 0:
        return None, None, None
    lead = effective_reorder_lead_days() if lead_days is None else max(0, int(lead_days))
    oos_d = date.fromisoformat(oos_iso)
    reorder_d = oos_d - timedelta(days=lead)
    qty = int(math.ceil(burn * lead)) if lead > 0 else 0
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
    reorder_cost_gbp: Optional[float] = None,
    sold_3m_units: int = 0,
    sold_1m_units: int = 0,
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
        "reorder_cost_gbp": reorder_cost_gbp,
        "sold_3m_units": sold_3m_units,
        "sold_1m_units": sold_1m_units,
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
            Order.cancel_status != "CANCELED",
            Order.date >= window_start,
            Order.date <= window_end,
        )
        .group_by(Order.date)
    )
    r = await db.execute(stmt)
    return {row[0]: int(row[1] or 0) for row in r.all()}


async def _sold_units_1m_3m(
    db: AsyncSession,
    line_item_skus: List[str],
) -> Tuple[int, int]:
    """Units sold over last 30 / 90 complete days (through yesterday), same windows as inventory sold columns."""
    if not line_item_skus:
        return 0, 0
    from_3m, to_sales = complete_days_range(90)
    from_1m, _ = complete_days_range(30)
    sales = await _ebay_units_by_order_date(db, line_item_skus, from_3m, to_sales)
    sold_3m = int(sum(sales.values()))
    sold_1m = int(sum(v for d, v in sales.items() if d >= from_1m))
    return sold_3m, sold_1m


def _sku_landed_cost_usd(sku_map: Dict[str, SKU], *codes: Optional[str]) -> Optional[float]:
    for raw in codes:
        code = (raw or "").strip()
        if not code:
            continue
        sku = sku_map.get(code)
        if sku and sku.landed_cost is not None:
            return float(sku.landed_cost)
    return None


async def _forecast_for_mapping_row(
    db: AsyncSession,
    connection_id: int,
    mapping: OCSkuMapping,
    window_start: date,
    window_end: date,
    sku_map: Dict[str, SKU],
    usd_to_gbp: float,
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

    line_skus = await _line_item_skus_for_mapping(db, connection_id, seller_skuid)
    sold_3m_units, sold_1m_units = await _sold_units_1m_3m(db, line_skus)

    stock_fields = dict(
        seller_skuid=seller_skuid,
        mfskuid=mfskuid,
        sku_name=sku_name,
        current_available=current_avl,
        current_in_transit=current_in_transit,
        current_received=current_received,
        ordered_total=ordered_total,
        sold_3m_units=sold_3m_units,
        sold_1m_units=sold_1m_units,
    )

    if ordered_total <= 0:
        return _forecast_row(**stock_fields)

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
    landed = _sku_landed_cost_usd(sku_map, mapping.sku_code, mapping.seller_skuid)
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
        reorder_cost_gbp=reorder_cost_gbp(reorder_qty, landed, usd_to_gbp),
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
    sku_codes: set[str] = set()
    for m in mappings:
        for raw in (m.sku_code, m.seller_skuid):
            code = (raw or "").strip()
            if code:
                sku_codes.add(code)
    sku_map: Dict[str, SKU] = {}
    if sku_codes:
        sr = await db.execute(select(SKU).where(SKU.sku_code.in_(sku_codes)))
        sku_map = {s.sku_code: s for s in sr.scalars().all()}
    usd_to_gbp = float(getattr(app_settings, "USD_TO_GBP_RATE", 0.79))
    rows = [
        await _forecast_for_mapping_row(
            db, connection_id, m, window_start, window_end, sku_map, usd_to_gbp
        )
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
