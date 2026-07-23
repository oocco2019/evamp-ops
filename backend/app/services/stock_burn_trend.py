"""
Burn-rate trend comparison: trailing 30 / 90 / 180 day windows ending at To date.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Literal, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.settings import OCSkuMapping
from app.models.stock import SKU
from app.services.stock_forecast import (
    MIN_AVL_IN_STOCK,
    _cover_and_oos,
    _daterange,
    _ebay_units_by_order_date,
    _latest_avl_actual_count,
    _latest_pipeline_counts,
    _line_item_skus_for_mapping,
    _reorder_plan,
    _sku_landed_cost_usd,
    average_burn_rate,
    forward_fill_daily_avl,
    reorder_cost_gbp,
)

VOLUME_GATE_UNITS = 15
LOW_SAMPLE_FRACTION = 0.6
COVER_DIVERGE_THRESHOLD = 0.30
OVERSTOCK_COVER_DAYS = 180

Verdict = Literal["accelerating", "stable", "decaying", "insufficient_volume"]
RatioSource = Literal[30, 90]


def effective_reorder_lead_days(
    lead: Optional[int] = None,
    buffer: Optional[int] = None,
) -> int:
    lead_v = int(lead if lead is not None else getattr(app_settings, "STOCK_REORDER_LEAD_TIME_DAYS", 90))
    buf_v = int(buffer if buffer is not None else getattr(app_settings, "STOCK_REORDER_BUFFER_DAYS", 0))
    return max(0, lead_v) + max(0, buf_v)


def window_start(to_date: date, days: int) -> date:
    """Inclusive trailing window of `days` calendar days ending on to_date."""
    return to_date - timedelta(days=days - 1)


def is_dead_burn_trend_row(
    available: int,
    ordered: int,
    burn_30: Optional[float],
    burn_90: Optional[float],
    burn_180: Optional[float],
) -> bool:
    """True when zero stock pipeline and no burn in any window."""
    if available > 0 or ordered > 0:
        return False
    for b in (burn_30, burn_90, burn_180):
        if b is not None and b > 0:
            return False
    return True


def cover_diverges(cover_30: Optional[float], cover_180: Optional[float], threshold: float = COVER_DIVERGE_THRESHOLD) -> bool:
    if cover_30 is None or cover_180 is None:
        return False
    m = max(abs(cover_30), abs(cover_180))
    if m <= 0:
        return False
    return abs(cover_30 - cover_180) / m > threshold


def is_low_sample(in_stock_days: int, window_length: int, fraction: float = LOW_SAMPLE_FRACTION) -> bool:
    return in_stock_days < fraction * window_length


def band_ratio(ratio: float) -> Literal["accelerating", "stable", "decaying"]:
    if ratio > 1.25:
        return "accelerating"
    if ratio >= 0.80:
        return "stable"
    return "decaying"


def evaluate_trend_verdict(
    *,
    burn_30: Optional[float],
    burn_90: Optional[float],
    burn_180: Optional[float],
    units_30: int,
    units_90: int,
    in_stock_days_30: int,
    in_stock_days_90: int,
    volume_gate: int = VOLUME_GATE_UNITS,
) -> Tuple[Optional[float], Optional[RatioSource], Optional[Verdict], bool]:
    """
    Returns (ratio, ratio_source, verdict, low_sample).

    30-day volume gate → band burn30/burn180.
    Else 90-day volume gate → ratio burn90/burn180, verdict insufficient_volume (not banded).
    Else no ratio / verdict.
    """
    if burn_180 is None or burn_180 <= 0:
        return None, None, None, False

    if units_30 >= volume_gate and burn_30 is not None and burn_30 > 0:
        ratio = burn_30 / burn_180
        verdict = band_ratio(ratio)
        low = is_low_sample(in_stock_days_30, 30)
        return round(ratio, 4), 30, verdict, low

    if units_90 >= volume_gate and burn_90 is not None and burn_90 > 0:
        ratio = burn_90 / burn_180
        low = is_low_sample(in_stock_days_90, 90)
        return round(ratio, 4), 90, "insufficient_volume", low

    return None, None, None, False


def reorder_suppressed(verdict: Optional[Verdict], cover_30: Optional[float]) -> bool:
    return verdict == "decaying" and cover_30 is not None and cover_30 > OVERSTOCK_COVER_DAYS


def burn_trend_note(to_date: date, lead_days: int) -> str:
    w30 = window_start(to_date, 30)
    w90 = window_start(to_date, 90)
    w180 = window_start(to_date, 180)
    return (
        f"Trailing windows ending {to_date.isoformat()}: 30d from {w30.isoformat()}, "
        f"90d from {w90.isoformat()}, 180d from {w180.isoformat()}. "
        f"Burn = eBay units ÷ in-stock days (AVL >= {MIN_AVL_IN_STOCK}). "
        f"Volume gate {VOLUME_GATE_UNITS} units in the short window; "
        f"low sample when in-stock days < {int(LOW_SAMPLE_FRACTION * 100)}% of window length. "
        f"Reorder lead {lead_days} days (config lead + buffer)."
    )


def _burn_for_window(
    daily_avl: Dict[date, int],
    sales_by_date: Dict[date, int],
    start: date,
    end: date,
) -> Tuple[Optional[float], int, int]:
    """Returns (burn_rate or None, in_stock_days, units_sold_in_window)."""
    days = _daterange(start, end)
    in_stock = [d for d in days if daily_avl.get(d, 0) >= MIN_AVL_IN_STOCK]
    units = int(sum(sales_by_date.get(d, 0) for d in days))
    daily_sales = [float(sales_by_date.get(d, 0)) for d in in_stock]
    burn = average_burn_rate(daily_sales)
    if burn <= 0:
        return None, len(in_stock), units
    return round(burn, 4), len(in_stock), units


async def _trend_row_for_mapping(
    db: AsyncSession,
    connection_id: int,
    mapping: OCSkuMapping,
    to_date: date,
    sku_map: Dict[str, SKU],
    usd_to_gbp: float,
    lead_days: int,
) -> dict:
    from app.api.inventory_status import list_inventory_history

    seller_skuid = (mapping.seller_skuid or "").strip()
    mfskuid = (mapping.mfskuid or "").strip()
    sku_name = (mapping.sku_code or "").strip() or seller_skuid
    region_filter = (mapping.service_region or "").strip() or None

    empty = {
        "seller_skuid": seller_skuid,
        "mfskuid": mfskuid,
        "sku_name": sku_name,
        "current_available": 0,
        "current_in_transit": 0,
        "current_received": 0,
        "ordered_total": 0,
        "burn_30": None,
        "burn_90": None,
        "burn_180": None,
        "in_stock_days_30": 0,
        "in_stock_days_90": 0,
        "in_stock_days_180": 0,
        "units_sold_30": 0,
        "units_sold_90": 0,
        "units_sold_180": 0,
        "ratio": None,
        "ratio_source": None,
        "verdict": None,
        "low_sample": False,
        "cover_30": None,
        "cover_180": None,
        "cover_diverge": False,
        "reorder_quantity": None,
        "reorder_by_date": None,
        "days_until_reorder": None,
        "reorder_cost_gbp": None,
        "reorder_suppressed": False,
        "overstocked": False,
        "is_dead": True,
    }

    if not mfskuid or not seller_skuid:
        return empty

    today = date.today()
    latest_avl = await _latest_avl_actual_count(db, connection_id, mfskuid, region_filter)
    current_avl = max(0, latest_avl) if latest_avl is not None else 0
    current_in_transit, current_received = await _latest_pipeline_counts(
        db, connection_id, mfskuid, region_filter
    )
    ordered_total = current_avl + current_in_transit + current_received

    start_180 = window_start(to_date, 180)
    start_90 = window_start(to_date, 90)
    start_30 = window_start(to_date, 30)

    hist = await list_inventory_history(
        db=db,
        from_date=start_180 - timedelta(days=120),
        to_date=to_date,
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

    daily = forward_fill_daily_avl(raw_pts, start_180, to_date)
    line_skus = await _line_item_skus_for_mapping(db, connection_id, seller_skuid)
    sales_by_date = await _ebay_units_by_order_date(db, line_skus, start_180, to_date)

    burn_30, isd_30, units_30 = _burn_for_window(daily, sales_by_date, start_30, to_date)
    burn_90, isd_90, units_90 = _burn_for_window(daily, sales_by_date, start_90, to_date)
    burn_180, isd_180, units_180 = _burn_for_window(daily, sales_by_date, start_180, to_date)

    ratio, ratio_source, verdict, low_sample = evaluate_trend_verdict(
        burn_30=burn_30,
        burn_90=burn_90,
        burn_180=burn_180,
        units_30=units_30,
        units_90=units_90,
        in_stock_days_30=isd_30,
        in_stock_days_90=isd_90,
    )

    cover_30, _ = (
        _cover_and_oos(ordered_total, burn_30, today) if burn_30 and burn_30 > 0 else (None, None)
    )
    cover_180, _ = (
        _cover_and_oos(ordered_total, burn_180, today) if burn_180 and burn_180 > 0 else (None, None)
    )
    # Actionable cover uses burn30; reorder from cover30 run-out when burn30 present, else burn180
    reorder_burn = burn_30 if burn_30 and burn_30 > 0 else burn_180
    _, oos_for_reorder = (
        _cover_and_oos(ordered_total, reorder_burn, today)
        if reorder_burn and reorder_burn > 0
        else (None, None)
    )
    reorder_qty, reorder_by, days_until = _reorder_plan(
        oos_for_reorder, reorder_burn or 0.0, today, lead_days=lead_days
    )
    landed = _sku_landed_cost_usd(sku_map, mapping.sku_code, mapping.seller_skuid)
    cost = reorder_cost_gbp(reorder_qty, landed, usd_to_gbp)

    suppressed = reorder_suppressed(verdict, cover_30)
    if suppressed:
        reorder_qty = None
        reorder_by = None
        days_until = None
        cost = None

    dead = is_dead_burn_trend_row(current_avl, ordered_total, burn_30, burn_90, burn_180)

    return {
        "seller_skuid": seller_skuid,
        "mfskuid": mfskuid,
        "sku_name": sku_name,
        "current_available": current_avl,
        "current_in_transit": current_in_transit,
        "current_received": current_received,
        "ordered_total": ordered_total,
        "burn_30": burn_30,
        "burn_90": burn_90,
        "burn_180": burn_180,
        "in_stock_days_30": isd_30,
        "in_stock_days_90": isd_90,
        "in_stock_days_180": isd_180,
        "units_sold_30": units_30,
        "units_sold_90": units_90,
        "units_sold_180": units_180,
        "ratio": ratio,
        "ratio_source": ratio_source,
        "verdict": verdict,
        "low_sample": low_sample,
        "cover_30": cover_30,
        "cover_180": cover_180,
        "cover_diverge": cover_diverges(cover_30, cover_180),
        "reorder_quantity": reorder_qty,
        "reorder_by_date": reorder_by,
        "days_until_reorder": days_until,
        "reorder_cost_gbp": cost,
        "reorder_suppressed": suppressed,
        "overstocked": suppressed,
        "is_dead": dead,
    }


async def build_stock_burn_trend_payload(
    db: AsyncSession,
    connection_id: int,
    to_date: date,
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
    lead_days = effective_reorder_lead_days()
    rows = [
        await _trend_row_for_mapping(db, connection_id, m, to_date, sku_map, usd_to_gbp, lead_days)
        for m in mappings
    ]
    rows.sort(
        key=lambda x: (
            1 if x.get("cover_30") is None else 0,
            float(x["cover_30"]) if x.get("cover_30") is not None else float("inf"),
        )
    )
    now = datetime.now(timezone.utc)
    return {
        "rows": rows,
        "generated_at": now.isoformat().replace("+00:00", "Z"),
        "note": burn_trend_note(to_date, lead_days),
        "to_date": to_date.isoformat(),
        "windows": {
            "d30": window_start(to_date, 30).isoformat(),
            "d90": window_start(to_date, 90).isoformat(),
            "d180": window_start(to_date, 180).isoformat(),
        },
        "reorder_lead_days": lead_days,
    }
