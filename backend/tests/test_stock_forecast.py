"""Unit tests for stock run-out forecast helpers."""
from datetime import date, datetime, time as dt_time

from app.services.stock_forecast import (
    _not_canceled_order_filter,
    forward_fill_daily_avl,
    weighted_burn_rate,
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


def test_weighted_burn_rate_linear_weights():
    """Oldest day weight 1, newest weight n."""
    assert weighted_burn_rate([2.0, 2.0, 2.0]) == 2.0
    # [1,2,3] -> (1*1 + 2*2 + 3*3) / (1+2+3) = 14/6
    assert abs(weighted_burn_rate([1.0, 2.0, 3.0]) - 14.0 / 6.0) < 1e-9


def test_weighted_burn_rate_empty():
    assert weighted_burn_rate([]) == 0.0


def test_stock_forecast_not_canceled_filter_includes_null_status():
    compiled = str(_not_canceled_order_filter().compile(compile_kwargs={"literal_binds": True}))

    assert "orders.cancel_status IS NULL" in compiled
    assert "orders.cancel_status != 'CANCELED'" in compiled
