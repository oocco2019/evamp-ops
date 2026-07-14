"""Unit tests for stock run-out forecast helpers."""
import asyncio
from datetime import date, datetime, time as dt_time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.settings import OCStockMovementLine, OCSkuInventory
from app.models.stock import LineItem, Order
from app.services.stock_forecast import (
    _cover_and_oos,
    _ebay_units_by_order_date,
    _latest_avl_actual_count,
    _latest_pipeline_counts,
    _reorder_plan,
    average_burn_rate,
    forecast_note,
    forward_fill_daily_avl,
)


class AsyncSessionShim:
    def __init__(self, session: Session):
        self.session = session

    async def execute(self, stmt):
        return self.session.execute(stmt)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


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


def test_regionless_forecast_counts_sum_latest_counts_across_regions(session):
    session.add_all(
        [
            OCStockMovementLine(
                connection_id=1,
                mfskuid="MF-1",
                service_region="UK",
                inventory_status="AVL",
                movement_id="UK-OLD",
                quantity=0,
                actual_count=4,
                update_time_raw="2026-01-01 10:00:00",
                update_time_utc=datetime(2026, 1, 1, 10, 0, 0),
            ),
            OCStockMovementLine(
                connection_id=1,
                mfskuid="MF-1",
                service_region="UK",
                inventory_status="AVL",
                movement_id="UK-NEW",
                quantity=0,
                actual_count=5,
                update_time_raw="2026-01-02 10:00:00",
                update_time_utc=datetime(2026, 1, 2, 10, 0, 0),
            ),
            OCStockMovementLine(
                connection_id=1,
                mfskuid="MF-1",
                service_region="DE",
                inventory_status="AVL",
                movement_id="DE-NEW",
                quantity=0,
                actual_count=7,
                update_time_raw="2026-01-03 10:00:00",
                update_time_utc=datetime(2026, 1, 3, 10, 0, 0),
            ),
            OCSkuInventory(
                connection_id=1,
                mfskuid="MF-1",
                service_region="UK",
                available=5,
                in_transit=10,
                received=1,
            ),
            OCSkuInventory(
                connection_id=1,
                mfskuid="MF-1",
                service_region="DE",
                available=7,
                in_transit=20,
                received=2,
            ),
        ]
    )
    session.commit()
    db = AsyncSessionShim(session)

    assert asyncio.run(_latest_avl_actual_count(db, 1, "mf-1", None)) == 12
    assert asyncio.run(_latest_avl_actual_count(db, 1, "mf-1", "UK")) == 5
    assert asyncio.run(_latest_pipeline_counts(db, 1, "mf-1", None)) == (30, 3)
    assert asyncio.run(_latest_pipeline_counts(db, 1, "mf-1", "UK")) == (10, 1)


def test_ebay_units_by_order_date_includes_null_cancel_status(session):
    uncanceled_null = Order(
        sales_channel="ebay",
        ebay_order_id="NULL-CANCEL",
        date=date(2026, 1, 5),
        country="GB",
        last_modified=datetime(2026, 1, 5, 12, 0, 0),
        cancel_status=None,
    )
    uncanceled_explicit = Order(
        sales_channel="ebay",
        ebay_order_id="NONE-REQUESTED",
        date=date(2026, 1, 5),
        country="GB",
        last_modified=datetime(2026, 1, 5, 13, 0, 0),
        cancel_status="NONE_REQUESTED",
    )
    canceled = Order(
        sales_channel="ebay",
        ebay_order_id="CANCELED",
        date=date(2026, 1, 5),
        country="GB",
        last_modified=datetime(2026, 1, 5, 14, 0, 0),
        cancel_status="CANCELED",
    )
    session.add_all([uncanceled_null, uncanceled_explicit, canceled])
    session.flush()
    session.add_all(
        [
            LineItem(order_id=uncanceled_null.order_id, ebay_line_item_id="L1", sku="SKU-A", quantity=2),
            LineItem(order_id=uncanceled_explicit.order_id, ebay_line_item_id="L2", sku="SKU-A", quantity=3),
            LineItem(order_id=canceled.order_id, ebay_line_item_id="L3", sku="SKU-A", quantity=99),
        ]
    )
    session.commit()

    sales = asyncio.run(
        _ebay_units_by_order_date(
            AsyncSessionShim(session),
            ["SKU-A"],
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
    )

    assert sales == {date(2026, 1, 5): 5}
