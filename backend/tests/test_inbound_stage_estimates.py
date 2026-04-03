import datetime

from app.api.inventory_status import (
    _inbound_status_is_canceled,
    _putaway_qty_transitioned,
    _should_set_arrived_at,
    _should_set_putaway_at,
    _status_indicates_arrived,
    _status_indicates_putaway,
)


def test_inbound_status_is_canceled():
    assert _inbound_status_is_canceled("Canceled") is True
    assert _inbound_status_is_canceled("Cancelled") is True
    assert _inbound_status_is_canceled("Put away") is False
    assert _inbound_status_is_canceled(None) is False


def test_status_indicates_putaway():
    assert _status_indicates_putaway("Put away") is True
    assert _status_indicates_putaway("Partially Put away") is True
    assert _status_indicates_putaway("putaway") is True
    assert _status_indicates_putaway("Not arrived") is False
    assert _status_indicates_putaway("") is False


def test_status_indicates_arrived():
    assert _status_indicates_arrived("Arrived") is True
    assert _status_indicates_arrived("Arrived (Completed)") is True
    assert _status_indicates_arrived("not arrived") is False
    assert _status_indicates_arrived("") is False
    assert _status_indicates_arrived("Put away") is False


def test_putaway_qty_transitioned():
    assert _putaway_qty_transitioned(prev_put_away_qty=0, new_put_away_qty=1) is True
    assert _putaway_qty_transitioned(prev_put_away_qty=0, new_put_away_qty=100) is True
    assert _putaway_qty_transitioned(prev_put_away_qty=5, new_put_away_qty=100) is False
    assert _putaway_qty_transitioned(prev_put_away_qty=10, new_put_away_qty=0) is False


def test_should_set_putaway_at_uses_qty_transition_when_status_unknown():
    assert (
        _should_set_putaway_at(
            existing_putaway_at=None,
            prev_put_away_qty=0,
            new_put_away_qty=100,
            prev_status_lower="in transit",
            status_lower="in transit",
        )
        is True
    )


def test_should_set_arrived_at_uses_qty_transition_as_proxy_when_status_not_arrived():
    assert (
        _should_set_arrived_at(
            existing_arrived_at=None,
            prev_put_away_qty=0,
            new_put_away_qty=100,
            prev_status_lower="in transit",
            status_lower="put away",
        )
        is True
    )


def test_should_not_set_when_already_set():
    existing_dt = datetime.datetime(2025, 1, 1)
    assert (
        _should_set_putaway_at(
            existing_putaway_at=existing_dt,
            prev_put_away_qty=0,
            new_put_away_qty=100,
            prev_status_lower="not put away",
            status_lower="put away",
        )
        is False
    )
    assert (
        _should_set_arrived_at(
            existing_arrived_at=existing_dt,
            prev_put_away_qty=0,
            new_put_away_qty=100,
            prev_status_lower="not arrived",
            status_lower="arrived",
        )
        is False
    )

