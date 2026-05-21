import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import inventory_status
from app.api.inventory_status import execute_oc_sku_mappings_sync


class _Result:
    def __init__(self, *, scalar_one=None, scalar_one_or_none=None):
        self._scalar_one = scalar_one
        self._scalar_one_or_none = scalar_one_or_none

    def scalar_one(self):
        return self._scalar_one

    def scalar_one_or_none(self):
        return self._scalar_one_or_none


class _FakeDb:
    def __init__(self, execute_results):
        self._execute_results = list(execute_results)
        self.execute_calls = []
        self.added = []
        self.committed = False
        self.rolled_back = False

    async def execute(self, statement):
        self.execute_calls.append(statement)
        if not self._execute_results:
            raise AssertionError(f"unexpected execute: {statement}")
        return self._execute_results.pop(0)

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True


def test_oc_sku_sync_preserves_existing_rows_when_oc_returns_empty(monkeypatch):
    async def empty_mappings(db):
        return []

    async def empty_inventory(db):
        return []

    monkeypatch.setattr(inventory_status, "oc_sync_sku_mappings", empty_mappings)
    monkeypatch.setattr(inventory_status, "oc_fetch_inventory_rows", empty_inventory)
    db = _FakeDb(
        [
            _Result(scalar_one_or_none=SimpleNamespace(id=42, region="UK")),
            _Result(scalar_one=3),
            _Result(scalar_one=3),
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(execute_oc_sku_mappings_sync(db))

    assert exc.value.status_code == 502
    assert "existing mappings were preserved" in exc.value.detail
    assert db.rolled_back is True
    assert db.committed is False
    assert db.added == []
    assert len(db.execute_calls) == 3
