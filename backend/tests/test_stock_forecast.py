"""Unit tests for stock run-out forecast helpers."""
import asyncio
from datetime import date, datetime, time as dt_time

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.models.settings import OCConnection, OCSkuInventory, OCStockMovementLine
from app.services.stock_forecast import (
    _cover_and_oos,
    _latest_avl_actual_count,
    _latest_pipeline_counts,
    _reorder_plan,
    average_burn_rate,
    forecast_note,
    forward_fill_daily_avl,
)


class SyncExecuteDb:
    def __init__(self, engine):
        self.session = Session(engine)

    async def execute(self, stmt):
        return self.session.execute(stmt)

    def close(self):
        self.session.close()


def _stock_tables_engine():
    engine = create_engine("sqlite:///:memory:")
    OCConnection.__table__.create(engine)
    OCSkuInventory.__table__.create(engine)
    OCStockMovementLine.__table__.create(engine)
    return engine


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


def test_cover_and_oos_does_not_overflow_for_slow_movers():
    doc, oos = _cover_and_oos(20_000, 1 / 180, date(2026, 6, 1))

    assert doc == 3_600_000.0
    assert oos is None


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


def test_latest_pipeline_counts_sum_all_regions_without_region_filter():
    engine = _stock_tables_engine()
    with Session(engine) as session:
        session.add_all(
            [
                OCSkuInventory(
                    connection_id=1,
                    mfskuid="MF1",
                    service_region="UK",
                    available=10,
                    in_transit=3,
                    received=5,
                ),
                OCSkuInventory(
                    connection_id=1,
                    mfskuid="MF1",
                    service_region="US-South",
                    available=4,
                    in_transit=7,
                    received=11,
                ),
            ]
        )
        session.commit()

    db = SyncExecuteDb(engine)
    try:
        assert asyncio.run(_latest_pipeline_counts(db, 1, "mf1", None)) == (10, 16)
        assert asyncio.run(_latest_pipeline_counts(db, 1, "mf1", "UK")) == (3, 5)
    finally:
        db.close()


def test_latest_avl_actual_count_sums_latest_per_region_without_region_filter():
    engine = _stock_tables_engine()
    with Session(engine) as session:
        session.add_all(
            [
                OCStockMovementLine(
                    connection_id=1,
                    mfskuid="MF1",
                    service_region="UK",
                    inventory_status="AVL",
                    movement_id="uk-old",
                    quantity=0,
                    actual_count=10,
                    update_time_raw="2026-06-01T10:00:00Z",
                    update_time_utc=datetime(2026, 6, 1, 10, 0, 0),
                ),
                OCStockMovementLine(
                    connection_id=1,
                    mfskuid="MF1",
                    service_region="UK",
                    inventory_status="AVL",
                    movement_id="uk-new",
                    quantity=0,
                    actual_count=8,
                    update_time_raw="2026-06-02T10:00:00Z",
                    update_time_utc=datetime(2026, 6, 2, 10, 0, 0),
                ),
                OCStockMovementLine(
                    connection_id=1,
                    mfskuid="MF1",
                    service_region="US-South",
                    inventory_status="AVL",
                    movement_id="us-new",
                    quantity=0,
                    actual_count=4,
                    update_time_raw="2026-06-02T11:00:00Z",
                    update_time_utc=datetime(2026, 6, 2, 11, 0, 0),
                ),
                OCStockMovementLine(
                    connection_id=1,
                    mfskuid="MF1",
                    service_region="UK",
                    inventory_status="INTRAN",
                    movement_id="ignored-status",
                    quantity=0,
                    actual_count=99,
                    update_time_raw="2026-06-03T10:00:00Z",
                    update_time_utc=datetime(2026, 6, 3, 10, 0, 0),
                ),
            ]
        )
        session.commit()

    db = SyncExecuteDb(engine)
    try:
        assert asyncio.run(_latest_avl_actual_count(db, 1, "mf1", None)) == 12
        assert asyncio.run(_latest_avl_actual_count(db, 1, "mf1", "UK")) == 8
    finally:
        db.close()
