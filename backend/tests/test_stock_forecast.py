"""Unit tests for stock run-out forecast helpers."""
import asyncio
from datetime import date, datetime, time as dt_time
from types import SimpleNamespace

from app.services import stock_forecast
from app.services.stock_forecast import (
    _cover_and_oos,
    _forecast_for_mapping_group,
    _mapping_groups_for_forecast,
    _reorder_plan,
    average_burn_rate,
    forecast_note,
    forward_fill_daily_avl,
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

    assert _cover_and_oos(0, 2.0, date(2026, 6, 1)) == (None, None)
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


def test_mapping_groups_for_forecast_collapses_same_seller_sku():
    mappings = [
        SimpleNamespace(seller_skuid="SELLER-1", mfskuid="MF-US", service_region="US"),
        SimpleNamespace(seller_skuid="seller-1", mfskuid="MF-UK", service_region="UK"),
        SimpleNamespace(seller_skuid="SELLER-2", mfskuid="MF-DE", service_region="DE"),
    ]

    groups = _mapping_groups_for_forecast(mappings)

    assert len(groups) == 2
    assert sorted(m.mfskuid for m in groups[0]) == ["MF-UK", "MF-US"]
    assert [m.mfskuid for m in groups[1]] == ["MF-DE"]


def test_forecast_for_mapping_group_applies_seller_sales_once(monkeypatch):
    mappings = [
        SimpleNamespace(seller_skuid="SELLER-1", mfskuid="MF-US", sku_code="SKU-A", service_region="US"),
        SimpleNamespace(seller_skuid="SELLER-1", mfskuid="MF-UK", sku_code="SKU-A", service_region="UK"),
    ]
    calls: dict[str, object] = {}

    async def fake_latest_avl_total(db, connection_id, mfskuids):
        calls["avl_mfskuids"] = list(mfskuids)
        return 100

    async def fake_pipeline_total(db, connection_id, mfskuids):
        calls["pipeline_mfskuids"] = list(mfskuids)
        return 20, 30

    async def fake_line_skus(db, connection_id, seller_skuid):
        calls["line_sku_seller"] = seller_skuid
        return ["SELLER-1", "SKU-A"]

    async def fake_sales(db, line_skus, window_start, window_end):
        calls["sales_line_skus"] = list(line_skus)
        return {date(2026, 1, 1): 2, date(2026, 1, 2): 2}

    async def fake_history(**kwargs):
        calls["history_seller"] = kwargs["seller_skuid"]
        return SimpleNamespace(
            points=[SimpleNamespace(recorded_at=datetime(2026, 1, 1, 0, 0, 0), available=100)]
        )

    from app.api import inventory_status

    monkeypatch.setattr(stock_forecast, "_latest_avl_actual_total", fake_latest_avl_total)
    monkeypatch.setattr(stock_forecast, "_latest_pipeline_counts_total", fake_pipeline_total)
    monkeypatch.setattr(stock_forecast, "_line_item_skus_for_mapping", fake_line_skus)
    monkeypatch.setattr(stock_forecast, "_ebay_units_by_order_date", fake_sales)
    monkeypatch.setattr(inventory_status, "list_inventory_history", fake_history)

    row = asyncio.run(
        _forecast_for_mapping_group(None, 1, mappings, date(2026, 1, 1), date(2026, 1, 2))
    )

    assert calls["avl_mfskuids"] == ["MF-UK", "MF-US"]
    assert calls["pipeline_mfskuids"] == ["MF-UK", "MF-US"]
    assert calls["history_seller"] == "SELLER-1"
    assert calls["line_sku_seller"] == "SELLER-1"
    assert calls["sales_line_skus"] == ["SELLER-1", "SKU-A"]
    assert row["seller_skuid"] == "SELLER-1"
    assert row["mfskuid"] == "MF-UK,MF-US"
    assert row["current_available"] == 100
    assert row["current_in_transit"] == 20
    assert row["current_received"] == 30
    assert row["ordered_total"] == 150
    assert row["burn_rate_per_day"] == 2.0
    assert row["total_sales_in_window"] == 4
