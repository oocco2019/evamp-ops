"""Unit tests for stock run-out forecast helpers."""
import asyncio
from datetime import date, datetime, time as dt_time
from types import SimpleNamespace

from app.services.stock_forecast import (
    average_burn_rate,
    forward_fill_daily_avl,
    forecast_note,
    _cover_and_oos,
    _forecast_for_mapping_row,
    _reorder_plan,
)


def test_forward_fill_daily_avl_resets_each_day_like_chart():
    """Each day uses last sample on or before end of day (not carried incorrectly from prior iteration bug)."""
    d0 = date(2026, 1, 1)
    t0 = datetime.combine(d0, dt_time(10, 0, 0))
    t1 = datetime.combine(d0, dt_time(15, 0, 0))
    d1 = date(2026, 1, 2)
    t2 = datetime.combine(d1, dt_time(12, 0, 0))
    pts = [(t0, 5), (t1, 10), (t2, 3)]
    out = forward_fill_daily_avl(pts, d0, d1)
    assert out[d0] == 10
    assert out[d1] == 3


def test_forward_fill_empty_points_zero():
    d0 = date(2026, 3, 1)
    d1 = date(2026, 3, 3)
    out = forward_fill_daily_avl([], d0, d1)
    assert out[d0] == 0 and out[d1] == 0


def test_average_burn_rate_simple_mean():
    assert average_burn_rate([2.0, 2.0, 2.0]) == 2.0
    assert average_burn_rate([1.0, 2.0, 3.0]) == 2.0


def test_average_burn_rate_empty():
    assert average_burn_rate([]) == 0.0


def test_forecast_note_mentions_avl_threshold():
    note = forecast_note(date(2026, 1, 1), date(2026, 6, 30))
    assert "AVL >= 7" in note
    assert "2026-01-01" in note


def test_cover_and_oos_ordered_total():
    doc, oos = _cover_and_oos(100, 2.0, date(2026, 6, 1))
    assert doc == 50.0
    assert oos == "2026-07-21"

    assert _cover_and_oos(0, 2.0, date(2026, 6, 1)) == (0.0, "2026-06-01")
    assert _cover_and_oos(10, 0.0, date(2026, 6, 1)) == (None, None)


def test_reorder_plan_three_month_lead():
    # Run-out 1 Dec → reorder 2 Sep; 2 units/day × 90 days = 180 units
    qty, reorder_by, days_until = _reorder_plan("2026-12-01", 2.0, date(2026, 6, 1), lead_days=90)
    assert qty == 180
    assert reorder_by == "2026-09-02"
    assert days_until == 93.0

    overdue_qty, overdue_by, overdue_days = _reorder_plan(
        "2026-08-01", 1.0, date(2026, 6, 1), lead_days=90
    )
    assert overdue_qty == 90
    assert overdue_by == "2026-05-03"
    assert overdue_days < 0


def test_zero_ordered_stock_still_gets_reorder_plan(monkeypatch):
    async def fake_latest_avl(*_args, **_kwargs):
        return 0

    async def fake_pipeline(*_args, **_kwargs):
        return 0, 0

    async def fake_line_item_skus(*_args, **_kwargs):
        return ["SKU-ZERO"]

    async def fake_sales(*_args, **_kwargs):
        return {
            date(2026, 1, 1): 2,
            date(2026, 1, 2): 2,
            date(2026, 1, 3): 2,
        }

    async def fake_history(*_args, **_kwargs):
        return SimpleNamespace(
            points=[
                SimpleNamespace(recorded_at=datetime(2026, 1, 1, 9, 0, 0), available=10),
            ]
        )

    monkeypatch.setattr("app.services.stock_forecast._latest_avl_actual_count", fake_latest_avl)
    monkeypatch.setattr("app.services.stock_forecast._latest_pipeline_counts", fake_pipeline)
    monkeypatch.setattr("app.services.stock_forecast._line_item_skus_for_mapping", fake_line_item_skus)
    monkeypatch.setattr("app.services.stock_forecast._ebay_units_by_order_date", fake_sales)
    monkeypatch.setattr("app.api.inventory_status.list_inventory_history", fake_history)

    mapping = SimpleNamespace(
        seller_skuid="SKU-ZERO",
        mfskuid="MFS-ZERO",
        sku_code="SKU-ZERO",
        service_region="UK",
    )

    row = asyncio.run(
        _forecast_for_mapping_row(
            db=SimpleNamespace(),
            connection_id=1,
            mapping=mapping,
            window_start=date(2026, 1, 1),
            window_end=date(2026, 1, 3),
        )
    )

    assert row["ordered_total"] == 0
    assert row["burn_rate_per_day"] == 2.0
    assert row["ordered_days_of_cover"] == 0.0
    assert row["ordered_estimated_oos_date"] == date.today().isoformat()
    assert row["reorder_quantity"] == 180
    assert row["days_until_reorder"] < 0
