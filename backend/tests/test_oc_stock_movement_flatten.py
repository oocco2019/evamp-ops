"""Tests for OC GetStockMovement response parsing and time window chunking."""
from datetime import datetime, timedelta, timezone

from app.services.oc_client import (
    _iter_movement_windows,
    flatten_stock_movement_response,
)


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
