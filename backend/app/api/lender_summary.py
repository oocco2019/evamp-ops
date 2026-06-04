"""
Lender summary: single read-only report (pre-tax gross profit) for external financial audiences.
Reuses _order_profit_gbp; revenue and profit use the same order inclusion rules as GET /analytics/order-details.
Units sold (headline, weekly breakdown, geography) match GET /api/stock/analytics/summary: sum of line quantities,
non-canceled orders in range (same as Sales Analytics, no extra filters). Time series is by week (Monday start).
"""
from __future__ import annotations

import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from typing import DefaultDict, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings as app_settings
from app.core.database import get_db
from app.api.stock import (
    _order_profit_gbp,
    _total_due_seller_gbp_amount,
    _not_canceled,
    _country_group,
)
from app.models.stock import Order, LineItem, SKU
from app.schemas.lender_summary import (
    HeadlineBlock,
    RollingPeriodRow,
    WeeklyRow,
    GeographyRow,
    MethodologyBlock,
    LenderSummaryResponse,
    LENDER_SUMMARY_DISCLOSURE,
    lender_reconciliation_errors,
)

router = APIRouter()

# Bump when LENDER_SUMMARY_DISCLOSURE or other API-visible copy changes, to invalidate in-process cache.
LENDER_SUMMARY_CACHE_VERSION = 5

_CACHE: Dict[Tuple[str, str, int], Tuple[float, LenderSummaryResponse]] = {}
_CACHE_TTL_SEC = 300


def _d2(s: Decimal) -> str:
    return str(s.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _monday_of_week(d: date) -> date:
    """Week starts Monday (Python weekday: Mon=0)."""
    return d - timedelta(days=d.weekday())


def _week_key(d: date) -> str:
    return _monday_of_week(d).isoformat()


def _week_label(week_start: date) -> str:
    """e.g. '6–12 Jan 2026' or '29 Dec 2025 – 4 Jan 2026'."""
    import calendar

    week_end = week_start + timedelta(days=6)

    def short(d: date) -> str:
        return f"{d.day} {calendar.month_abbr[d.month]}"

    if week_start.year == week_end.year and week_start.month == week_end.month:
        return (
            f"{week_start.day}–{week_end.day} "
            f"{calendar.month_name[week_start.month]} {week_start.year}"
        )
    return f"{short(week_start)} – {short(week_end)} {week_end.year}"


def _week_list_inclusive(frm: date, to: date) -> List[Tuple[str, str]]:
    """[(week_start ISO Monday, display label), ...] oldest first."""
    m0 = _monday_of_week(frm)
    m1 = _monday_of_week(to)
    out: List[Tuple[str, str]] = []
    cur = m0
    while cur <= m1:
        out.append((cur.isoformat(), _week_label(cur)))
        cur += timedelta(weeks=1)
    return out


def _is_full_week_in_range(week_start: date, frm: date, to: date) -> bool:
    """True if the whole Mon–Sun week lies inside [frm, to] (inclusive)."""
    week_end = week_start + timedelta(days=6)
    return week_start >= frm and week_end <= to


def _orders_in_rolling_window(
    orders: List[Order], to: date, window_days: int
) -> List[Order]:
    """Inclusive window of `window_days` calendar days ending on `to`."""
    start = to - timedelta(days=window_days - 1)
    return [o for o in orders if start <= o.date <= to]


def _process_order_for_lender(
    o: Order,
    sku_map: Dict[str, SKU],
    usd_to_gbp: float,
) -> Optional[Tuple[Decimal, Decimal, Decimal]]:
    price_total = o.price_total or Decimal(0)
    if price_total == 0 or o.total_due_seller is None:
        return None

    line_items = list(o.line_items)
    if not line_items:
        return None

    line_cost_usd = Decimal(0)
    line_postage_usd = Decimal(0)
    for li in o.line_items:
        s = sku_map.get(li.sku) if li.sku else None
        landed = (s.landed_cost or Decimal(0)) if s else Decimal(0)
        postage = (s.postage_price or Decimal(0)) if s else Decimal(0)
        qty = li.quantity or 0
        line_cost_usd += (landed + postage) * qty
        line_postage_usd += postage * qty

    op = _order_profit_gbp(
        o.total_due_seller,
        o.total_due_seller_currency,
        o.price_total,
        o.tax_total,
        o.order_currency,
        o.country,
        line_cost_usd,
        line_postage_usd,
        usd_to_gbp,
        sales_channel=o.sales_channel,
    )
    if op is None:
        return None
    td = _total_due_seller_gbp_amount(
        o.total_due_seller, o.total_due_seller_currency, o.order_currency
    )
    if td is None:
        return None

    return (td, op, price_total)


def _geo_bucket(o: Order) -> str:
    cg = _country_group(o.country)
    if cg in ("GB",):
        return "UK"
    if cg == "DE":
        return "DE"
    if cg == "US":
        return "US"
    return "OTHER"


def aggregate_lender_snapshot(
    orders: List[Order],
    sku_map: Dict[str, SKU],
    usd_to_gbp: float,
    from_date: date,
    to_date: date,
) -> LenderSummaryResponse:
    """
    Revenue and gross profit: same rules as order-details (payout + costs + VAT).
    Units: same as /api/stock/analytics/summary — all line quantities on non-canceled orders in range.
    `orders` may span past `from_date` (e.g. for 180d rolling) — headline / weekly / geo use only
    [from_date, to_date].
    """
    report_orders = [o for o in orders if from_date <= o.date <= to_date]

    analytics_units_total = 0
    units_by_week: DefaultDict[str, int] = defaultdict(int)
    units_by_geo: DefaultDict[str, int] = defaultdict(int)
    for o in report_orders:
        wkey = _week_key(o.date)
        gkey = _geo_bucket(o)
        for li in o.line_items:
            q = li.quantity or 0
            analytics_units_total += q
            units_by_week[wkey] += q
            units_by_geo[gkey] += q

    total_td = Decimal(0)
    total_op = Decimal(0)

    by_week: DefaultDict[str, Dict[str, Decimal]] = defaultdict(
        lambda: {"rev": Decimal(0), "op": Decimal(0)}
    )
    by_geo: DefaultDict[str, Dict[str, Decimal]] = defaultdict(
        lambda: {"rev": Decimal(0), "op": Decimal(0)}
    )

    for o in report_orders:
        proc = _process_order_for_lender(o, sku_map, usd_to_gbp)
        if proc is None:
            continue
        td_gbp, op_g, _price_total = proc
        wkey = _week_key(o.date)
        total_td += td_gbp
        total_op += op_g

        by_week[wkey]["rev"] = Decimal(str(by_week[wkey]["rev"])) + td_gbp
        by_week[wkey]["op"] = Decimal(str(by_week[wkey]["op"])) + op_g

        gkey = _geo_bucket(o)
        bg = by_geo[gkey]
        bg["rev"] = Decimal(str(bg["rev"])) + td_gbp
        bg["op"] = Decimal(str(bg["op"])) + op_g

    # Full weeks only (Mon–Sun fully inside the report range); omit clipped edge weeks in chart/table
    week_keys = _week_list_inclusive(from_date, to_date)
    complete_weeks = [
        (k, lab)
        for k, lab in week_keys
        if _is_full_week_in_range(date.fromisoformat(k), from_date, to_date)
    ]
    weekly_rows: List[WeeklyRow] = []
    for key, wlabel in complete_weeks:
        b = by_week.get(
            key, {"rev": Decimal(0), "op": Decimal(0)}
        )
        u = int(units_by_week.get(key, 0))
        rev = Decimal(str(b["rev"]))
        op_ = Decimal(str(b["op"]))
        rev_s = _d2(rev)
        op_s = _d2(op_)
        margin = (
            (op_ / rev * Decimal(100)) if rev > 0 else Decimal(0)
        )
        weekly_rows.append(
            WeeklyRow(
                week_start=key,
                week_label=wlabel,
                units=u,
                revenue_gbp=rev_s,
                gross_profit_gbp=op_s,
                margin_percent=_d2(margin),
            )
        )

    rolling_specs: List[Tuple[int, str]] = [
        (30, "Last 30 days"),
        (90, "Last 90 days"),
        (180, "Last 180 days"),
    ]
    rolling_rows: List[RollingPeriodRow] = []
    for window_days, rlabel in rolling_specs:
        win = _orders_in_rolling_window(orders, to_date, window_days)
        ru = 0
        for o in win:
            for li in o.line_items:
                ru += li.quantity or 0
        rtd = Decimal(0)
        rop = Decimal(0)
        for o in win:
            proc = _process_order_for_lender(o, sku_map, usd_to_gbp)
            if proc is None:
                continue
            td_gbp, op_g, _ = proc
            rtd += td_gbp
            rop += op_g
        p_start = to_date - timedelta(days=window_days - 1)
        margin_r = (rop / rtd * Decimal(100)) if rtd > 0 else Decimal(0)
        rolling_rows.append(
            RollingPeriodRow(
                label=rlabel,
                window_days=window_days,
                period_start=p_start.isoformat(),
                period_end=to_date.isoformat(),
                units=ru,
                revenue_gbp=_d2(rtd),
                gross_profit_gbp=_d2(rop),
                margin_percent=_d2(margin_r),
            )
        )

    # Geography table: US, UK, DE, Other — order by revenue desc
    geo_order: List[Tuple[str, str, str]] = [
        ("UK", "United Kingdom", "UK"),
        ("DE", "Germany", "DE"),
        ("US", "United States", "US"),
        ("OTHER", "Other", "OTHER"),
    ]
    geo_buf: List[Tuple[str, str, int, Decimal, Decimal]] = []
    for gkey, label, _code in geo_order:
        b = by_geo.get(
            gkey, {"rev": Decimal(0), "op": Decimal(0)}
        )
        u = int(units_by_geo.get(gkey, 0))
        rev = Decimal(str(b["rev"]))
        op_ = Decimal(str(b["op"]))
        geo_buf.append((label, gkey, u, rev, op_))
    geo_buf.sort(key=lambda r: -r[3])
    geos: List[GeographyRow] = []
    acc_gr = Decimal(0)
    acc_go = Decimal(0)
    for i, (label, gkey, u, rev, op_) in enumerate(geo_buf):
        is_last = i == len(geo_buf) - 1
        if is_last:
            rev_s = _d2(total_td - acc_gr)
            op_s = _d2(total_op - acc_go)
        else:
            rev_s = _d2(rev)
            op_s = _d2(op_)
            acc_gr += Decimal(rev_s)
            acc_go += Decimal(op_s)
        pct = (
            (Decimal(rev_s) / total_td * Decimal(100)) if total_td > 0 else Decimal(0)
        )
        geos.append(
            GeographyRow(
                label=label,
                code=gkey,
                units=u,
                revenue_gbp=rev_s,
                gross_profit_gbp=op_s,
                pct_of_total_revenue=_d2(pct),
            )
        )

    margin_h = (total_op / total_td * Decimal(100)) if total_td > 0 else Decimal(0)
    now = datetime.utcnow().replace(microsecond=0)
    out = LenderSummaryResponse(
        period_from=from_date.isoformat(),
        period_to=to_date.isoformat(),
        generated_at_utc=now.isoformat() + "Z",
        disclosure=LENDER_SUMMARY_DISCLOSURE,
        headline=HeadlineBlock(
            units_sold=analytics_units_total,
            gross_revenue_gbp=_d2(total_td),
            gross_profit_pre_tax_gbp=_d2(total_op),
            gross_margin_percent=_d2(margin_h),
        ),
        weekly=weekly_rows,
        rolling_periods=rolling_rows,
        geography=geos,
        methodology=MethodologyBlock(
            usd_to_gbp_rate=float(getattr(app_settings, "USD_TO_GBP_RATE", 0.79)),
            eur_to_gbp_rate=float(getattr(app_settings, "EUR_TO_GBP_RATE", 0.86)),
            uk_vat_default_rate=float(
                getattr(app_settings, "UK_VAT_DEFAULT_RATE", 0.20)
            ),
            generated_at_utc=now.isoformat() + "Z",
        ),
    )
    rec = lender_reconciliation_errors(out)
    if rec:
        raise ValueError("lender summary reconciliation failed: " + "; ".join(rec))
    return out


async def build_lender_summary_payload(
    db: AsyncSession,
    from_date: date,
    to_date: date,
) -> LenderSummaryResponse:
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be <= to")

    # Need up to 180d before `to` for rolling period rows; still cap headline/weekly/geo to [from, to] in aggregate.
    query_from = min(from_date, to_date - timedelta(days=179))

    stmt = (
        select(Order)
        .options(selectinload(Order.line_items))
        .where(Order.date >= query_from, Order.date <= to_date, _not_canceled())
    )
    result = await db.execute(stmt)
    orders = result.scalars().unique().all()

    sku_codes: set = set()
    for o in orders:
        for li in o.line_items:
            if li.sku:
                sku_codes.add(li.sku)
    sku_map: dict = {}
    if sku_codes:
        sku_result = await db.execute(select(SKU).where(SKU.sku_code.in_(sku_codes)))
        sku_map = {s.sku_code: s for s in sku_result.scalars().all()}

    usd_to_gbp = float(getattr(app_settings, "USD_TO_GBP_RATE", 0.79))
    return aggregate_lender_snapshot(orders, sku_map, usd_to_gbp, from_date, to_date)


@router.get("/lender-summary", response_model=LenderSummaryResponse)
async def get_lender_summary(
    from_date: date = Query(..., alias="from", description="Start date (YYYY-MM-DD)"),
    to_date: date = Query(..., alias="to", description="End date (YYYY-MM-DD)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Lender report: pre-tax gross profit (same gross rules as /analytics/order-details, without PROFIT_TAX scaling).
    Cached 5 minutes per (from, to).
    """
    if from_date > to_date:
        raise HTTPException(status_code=400, detail="from must be <= to")
    k = (from_date.isoformat(), to_date.isoformat(), LENDER_SUMMARY_CACHE_VERSION)
    now = time.time()
    if k in _CACHE and _CACHE[k][0] > now:
        return _CACHE[k][1]
    data = await build_lender_summary_payload(db, from_date, to_date)
    _CACHE[k] = (now + _CACHE_TTL_SEC, data)
    return data
