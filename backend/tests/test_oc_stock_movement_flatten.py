"""Tests for OC GetStockMovement response parsing, auth rotation, and time windows."""
import asyncio
from datetime import datetime, timedelta, timezone

from app.core.security import encryption_service
from app.models.settings import APICredential
from app.services.oc_client import (
    _persist_oc_refresh_token_if_rotated,
    _iter_movement_windows,
    clamp_oc_movement_query_bounds,
    flatten_stock_movement_response,
)


class _ScalarResult:
    def __init__(self, row):
        self.row = row

    def scalar_one_or_none(self):
        return self.row


class _FakeDb:
    def __init__(self, row):
        self.row = row
        self.flushed = 0
        self.committed = 0

    async def execute(self, _stmt):
        return _ScalarResult(self.row)

    async def flush(self):
        self.flushed += 1

    async def commit(self):
        self.committed += 1


def test_persist_oc_refresh_token_rotation_commits_immediately():
    row = APICredential(
        service_name="oc",
        key_name="refresh_token",
        encrypted_value=encryption_service.encrypt("old-refresh"),
        is_active=True,
    )
    db = _FakeDb(row)

    asyncio.run(
        _persist_oc_refresh_token_if_rotated(
            db,
            {"refresh_token": "new-refresh"},
            "https://oauth.example",
            "client-id",
        )
    )

    assert encryption_service.decrypt(row.encrypted_value) == "new-refresh"
    assert db.flushed == 1
    assert db.committed == 1


def test_flatten_stock_movement_success_example():
    resp = {
        "code": 0,
        "message": "成功",
        "data": [
            {
                "MFSKUID": "OC1",
                "sellerSkuId": "S1",
                "serviceRegionList": [
                    {
                        "serviceRegion": "DE",
                        "inventoryList": [
                            {
                                "inventoryStatus": "AVL",
                                "movementList": [
                                    {
                                        "actualCount": 0,
                                        "moventmentID": "m1",
                                        "quantity": -20,
                                        "reason": "OEH",
                                        "updateTime": "2024-07-15T19:48:37+0800",
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    rows = flatten_stock_movement_response(resp)
    assert len(rows) == 1
    assert rows[0]["mfskuid"] == "OC1"
    assert rows[0]["seller_skuid"] == "S1"
    assert rows[0]["service_region"] == "DE"
    assert rows[0]["inventory_status"] == "AVL"
    assert rows[0]["movement_id"] == "m1"
    assert rows[0]["quantity"] == -20
    assert rows[0]["actual_count"] == 0
    assert rows[0]["update_time"] == "2024-07-15T19:48:37+0800"


def test_flatten_errors_returns_empty():
    resp = {"code": 3, "errors": [{"message": "bad"}]}
    assert flatten_stock_movement_response(resp) == []


def test_iter_movement_windows_under_seven_days():
    start = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2025, 1, 10, 23, 59, 59, tzinfo=timezone.utc)
    wins = _iter_movement_windows(start, end)
    assert len(wins) >= 2
    for a, b in wins:
        assert a <= b
        assert (b - a) <= timedelta(days=7)


def test_iter_movement_windows_single_day():
    start = datetime(2025, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    end = datetime(2025, 6, 1, 12, 30, 0, tzinfo=timezone.utc)
    wins = _iter_movement_windows(start, end)
    assert len(wins) == 1
    assert wins[0] == (start, end)


def test_clamp_raises_old_start_to_lookback():
    ref = datetime(2026, 6, 15, 12, 0, 0, tzinfo=timezone.utc)
    start = datetime(2020, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 6, 10, 23, 59, 59, tzinfo=timezone.utc)
    s, e = clamp_oc_movement_query_bounds(start, end, reference_time=ref)
    assert s == ref - timedelta(days=365)
    assert e == end


def test_clamp_caps_end_to_reference_now():
    ref = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
    start = datetime(2025, 6, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2027, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    s, e = clamp_oc_movement_query_bounds(start, end, reference_time=ref)
    assert e == ref
    assert s >= ref - timedelta(days=365)


def test_clamp_empty_range_when_entirely_before_window():
    ref = datetime(2026, 1, 10, 12, 0, 0, tzinfo=timezone.utc)
    start = datetime(2018, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    end = datetime(2019, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    s, e = clamp_oc_movement_query_bounds(start, end, reference_time=ref)
    assert s >= e
