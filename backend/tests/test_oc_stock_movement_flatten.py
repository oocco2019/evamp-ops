"""Tests for OC GetStockMovement response parsing and time window chunking."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models.settings import OCStockMovementLine
from app.services.oc_client import (
    _iter_movement_windows,
    clamp_oc_movement_query_bounds,
    flatten_stock_movement_response,
)
from app.services import oc_stock_movement_store


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


def test_stock_movement_unique_constraint_uses_full_line_identity():
    constraint = next(
        c
        for c in OCStockMovementLine.__table__.constraints
        if c.name == "uq_oc_stock_mov_conn_movement_identity"
    )

    assert [col.name for col in constraint.columns] == [
        "connection_id",
        "movement_id",
        "mfskuid",
        "service_region",
        "update_time_raw",
    ]


@pytest.mark.asyncio
async def test_persist_stock_movements_allows_same_movement_id_for_distinct_lines(monkeypatch):
    captured = []

    class FakeInsert:
        def __init__(self):
            self.values_payload = []
            self.conflict_constraint = None

        def values(self, payload):
            self.values_payload = payload
            return self

        def on_conflict_do_nothing(self, *, constraint):
            self.conflict_constraint = constraint
            return self

    class FakeResult:
        def __init__(self, rowcount):
            self.rowcount = rowcount

    class FakeDb:
        async def execute(self, stmt):
            captured.append(stmt)
            return FakeResult(len(stmt.values_payload))

    def fake_pg_insert(model):
        assert model is OCStockMovementLine
        return FakeInsert()

    monkeypatch.setattr(oc_stock_movement_store, "pg_insert", fake_pg_insert)

    inserted = await oc_stock_movement_store.persist_oc_stock_movement_lines(
        FakeDb(),
        7,
        [
            {
                "movement_id": "MOVE-1",
                "mfskuid": "MF-1",
                "service_region": "UK",
                "inventory_status": "AVL",
                "quantity": -1,
                "actual_count": 10,
                "update_time": "2026-01-01T12:00:00+0000",
            },
            {
                "movement_id": "MOVE-1",
                "mfskuid": "MF-2",
                "service_region": "DE",
                "inventory_status": "AVL",
                "quantity": -2,
                "actual_count": 5,
                "update_time": "2026-01-01T12:00:00+0000",
            },
        ],
    )

    assert inserted == 2
    assert len(captured) == 1
    assert captured[0].conflict_constraint == "uq_oc_stock_mov_conn_movement_identity"
    assert [p["mfskuid"] for p in captured[0].values_payload] == ["MF-1", "MF-2"]
