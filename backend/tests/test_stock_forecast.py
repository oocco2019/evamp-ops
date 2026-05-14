"""Unit tests for stock run-out forecast helpers."""
from datetime import date, datetime, time as dt_time

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.models.stock import LineItem, Order
from app.services.order_filters import order_not_canceled_condition
from app.services.stock_forecast import forward_fill_daily_avl, weighted_burn_rate


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


def test_weighted_burn_rate_linear_weights():
    """Oldest day weight 1, newest weight n."""
    assert weighted_burn_rate([2.0, 2.0, 2.0]) == 2.0
    # [1,2,3] -> (1*1 + 2*2 + 3*3) / (1+2+3) = 14/6
    assert abs(weighted_burn_rate([1.0, 2.0, 3.0]) - 14.0 / 6.0) < 1e-9


def test_weighted_burn_rate_empty():
    assert weighted_burn_rate([]) == 0.0


def test_order_sales_filter_includes_null_cancel_status_orders():
    """Shopify open orders use NULL cancel_status and must count toward stock burn."""
    engine = create_engine("sqlite:///:memory:")
    Order.__table__.create(engine)
    LineItem.__table__.create(engine)
    order_date = date(2026, 5, 14)
    modified_at = datetime(2026, 5, 14, 10, 0, 0)

    with Session(engine) as session:
        shopify_open = Order(
            sales_channel="shopify",
            ebay_order_id="shopify-open",
            date=order_date,
            country="GB",
            last_modified=modified_at,
            cancel_status=None,
        )
        ebay_open = Order(
            sales_channel="ebay",
            ebay_order_id="ebay-open",
            date=order_date,
            country="GB",
            last_modified=modified_at,
            cancel_status="NONE_REQUESTED",
        )
        canceled = Order(
            sales_channel="shopify",
            ebay_order_id="shopify-canceled",
            date=order_date,
            country="GB",
            last_modified=modified_at,
            cancel_status="CANCELED",
        )
        session.add_all([shopify_open, ebay_open, canceled])
        session.flush()
        session.add_all(
            [
                LineItem(order_id=shopify_open.order_id, ebay_line_item_id="li-1", sku="SKU-1", quantity=2),
                LineItem(order_id=ebay_open.order_id, ebay_line_item_id="li-2", sku="SKU-1", quantity=3),
                LineItem(order_id=canceled.order_id, ebay_line_item_id="li-3", sku="SKU-1", quantity=11),
            ]
        )
        session.commit()

        units = session.execute(
            select(func.coalesce(func.sum(LineItem.quantity), 0))
            .select_from(LineItem)
            .join(Order, Order.order_id == LineItem.order_id)
            .where(LineItem.sku == "SKU-1", order_not_canceled_condition())
        ).scalar_one()

    assert units == 5
