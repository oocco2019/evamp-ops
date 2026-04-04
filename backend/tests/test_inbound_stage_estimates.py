import datetime

from app.api.inventory_status import (
    _extract_inbound_ui_times,
    _inbound_status_is_canceled,
    _putaway_qty_transitioned,
    _should_set_arrived_at,
    _should_set_putaway_at,
    _status_indicates_arrived,
    _status_indicates_other_warehouse,
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
    assert _status_indicates_putaway("Inbound Complete") is True
    assert _status_indicates_putaway("Goods Received") is True
    assert _status_indicates_putaway("Checked in warehouse") is True
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


def test_extract_inbound_ui_times_putaway_db_only_when_eligible_putaway_status():
    """First-seen since yesterday UTC: putaway status uses putaway_at for Putaway column; not Arrived."""
    now = datetime.datetime(2026, 4, 4, 12, 0, 0)
    fs = datetime.datetime(2026, 4, 3, 10, 0, 0)
    putaway_est = datetime.datetime(2026, 4, 3, 8, 15, 54)
    raw = {"status": "Put away"}
    create_s, putaway_s, arrived_s = _extract_inbound_ui_times(
        raw,
        inbound_at_db=fs,
        putaway_at_db=putaway_est,
        arrived_at_db=None,
        status_from_row="Put away",
        now_utc_naive=now,
    )
    assert create_s is not None
    assert putaway_s == putaway_est.strftime("%Y-%m-%d %H:%M:%S")
    assert arrived_s is None


def test_extract_inbound_ui_times_no_db_putaway_when_first_seen_too_old():
    """Before yesterday UTC cutoff: do not surface sync-time putaway_at as Putaway display."""
    putaway_est = datetime.datetime(2025, 6, 10, 8, 0, 0)
    inbound_at = datetime.datetime(2025, 5, 1, 12, 0, 0)
    now = datetime.datetime(2026, 4, 4, 12, 0, 0)
    raw = {"status": "Put away"}
    _, putaway_s, arrived_s = _extract_inbound_ui_times(
        raw,
        inbound_at_db=inbound_at,
        putaway_at_db=putaway_est,
        arrived_at_db=None,
        status_from_row="Put away",
        now_utc_naive=now,
    )
    assert putaway_s is None
    assert arrived_s is None


def test_extract_inbound_ui_times_no_proxy_when_in_transit():
    putaway_est = datetime.datetime(2025, 6, 10, 8, 0, 0)
    now = datetime.datetime(2026, 4, 4, 12, 0, 0)
    raw = {"status": "In transit"}
    _, _, arrived_s = _extract_inbound_ui_times(
        raw,
        inbound_at_db=datetime.datetime(2026, 4, 3, 12, 0, 0),
        putaway_at_db=putaway_est,
        arrived_at_db=None,
        status_from_row="In transit",
        now_utc_naive=now,
    )
    assert arrived_s is None


def test_extract_inbound_ui_times_proxy_uses_raw_putaway_when_inbound_complete_status():
    raw = {"status": "Inbound Complete", "putAwayTime": "2025-07-01 10:00:00"}
    create_s, putaway_s, arrived_s = _extract_inbound_ui_times(
        raw,
        inbound_at_db=datetime.datetime(2025, 5, 1, 12, 0, 0),
        putaway_at_db=None,
        arrived_at_db=None,
    )
    assert putaway_s is not None
    assert arrived_s == putaway_s


def test_extract_inbound_ui_times_arrived_db_when_eligible_arrived_status():
    now = datetime.datetime(2026, 4, 4, 12, 0, 0)
    fs = datetime.datetime(2026, 4, 3, 9, 0, 0)
    arr = datetime.datetime(2026, 4, 3, 14, 0, 0)
    raw = {"status": "Arrived"}
    _, _, arrived_s = _extract_inbound_ui_times(
        raw,
        inbound_at_db=fs,
        putaway_at_db=None,
        arrived_at_db=arr,
        status_from_row="Arrived",
        now_utc_naive=now,
    )
    assert arrived_s == arr.strftime("%Y-%m-%d %H:%M:%S")


def test_extract_inbound_ui_times_other_warehouse_uses_arrived_or_putaway_db():
    now = datetime.datetime(2026, 4, 4, 12, 0, 0)
    fs = datetime.datetime(2026, 4, 3, 9, 0, 0)
    pa = datetime.datetime(2026, 4, 3, 11, 0, 0)
    raw = {"status": "Processing"}
    _, _, arrived_s = _extract_inbound_ui_times(
        raw,
        inbound_at_db=fs,
        putaway_at_db=pa,
        arrived_at_db=None,
        status_from_row="Processing",
        now_utc_naive=now,
    )
    assert arrived_s == pa.strftime("%Y-%m-%d %H:%M:%S")


def test_status_indicates_other_warehouse():
    assert _status_indicates_other_warehouse("Processing") is True
    assert _status_indicates_other_warehouse("Put away") is False
    assert _status_indicates_other_warehouse("Arrived") is False
    assert _status_indicates_other_warehouse("In transit") is False

