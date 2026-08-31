"""Unit tests for movement-derived inventory history series assembly."""
from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.api import inventory_status


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, *results):
        self._results = list(results)

    async def execute(self, _statement):
        if not self._results:
            raise AssertionError("unexpected execute call")
        return self._results.pop(0)


@pytest.mark.asyncio
async def test_inventory_history_emits_opening_point_from_seed(monkeypatch):
    async def active_connection_id(_db):
        return 1

    async def resolve_mfsku_list(_db, _cid, _seller_skuid, _sku_code, _mfskuid):
        return ["M1"], "filtered"

    monkeypatch.setattr(inventory_status, "_active_oc_connection_id", active_connection_id)
    monkeypatch.setattr(inventory_status, "_resolve_mfsku_list_for_movement", resolve_mfsku_list)

    db = _FakeDb(
        _FakeResult([SimpleNamespace(mfskuid="M1", service_region="DE", avl_after=12)]),
        _FakeResult([]),
    )

    response = await inventory_status.list_inventory_history(
        db=db,
        from_date=date(2026, 4, 10),
        to_date=date(2026, 4, 12),
        mfskuid="M1",
    )

    assert len(response.points) == 1
    assert response.points[0].recorded_at == datetime(2026, 4, 10, 0, 0)
    assert response.points[0].available == 12
    assert response.points[0].stockout is False


@pytest.mark.asyncio
async def test_inventory_history_opening_point_precedes_later_bursts(monkeypatch):
    async def active_connection_id(_db):
        return 1

    async def resolve_mfsku_list(_db, _cid, _seller_skuid, _sku_code, _mfskuid):
        return ["M1"], "filtered"

    monkeypatch.setattr(inventory_status, "_active_oc_connection_id", active_connection_id)
    monkeypatch.setattr(inventory_status, "_resolve_mfsku_list_for_movement", resolve_mfsku_list)

    db = _FakeDb(
        _FakeResult([SimpleNamespace(mfskuid="M1", service_region="DE", avl_after=12)]),
        _FakeResult(
            [
                SimpleNamespace(
                    ts=datetime(2026, 4, 12, 9, 30),
                    mfskuid="M1",
                    service_region="DE",
                    avl_after=8,
                )
            ]
        ),
    )

    response = await inventory_status.list_inventory_history(
        db=db,
        from_date=date(2026, 4, 10),
        to_date=date(2026, 4, 12),
        mfskuid="M1",
    )

    assert [p.recorded_at for p in response.points] == [
        datetime(2026, 4, 10, 0, 0),
        datetime(2026, 4, 12, 9, 30),
    ]
    assert [p.available for p in response.points] == [12, 8]
