import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import inventory_status


class _FakeResult:
    def __init__(self, *, one_or_none=None, one=None):
        self._one_or_none = one_or_none
        self._one = one

    def scalar_one_or_none(self):
        return self._one_or_none

    def scalar_one(self):
        return self._one


class _FakeDb:
    def __init__(self, results):
        self._results = list(results)
        self.statements = []
        self.committed = False

    async def execute(self, statement):
        self.statements.append(statement)
        return self._results.pop(0) if self._results else _FakeResult()

    def add(self, _row):
        pass

    async def commit(self):
        self.committed = True


def test_oc_sku_sync_preserves_existing_cache_on_empty_oc_payload(monkeypatch):
    async def empty_mappings(_db):
        return []

    async def empty_inventory(_db):
        return []

    monkeypatch.setattr(inventory_status, "oc_sync_sku_mappings", empty_mappings)
    monkeypatch.setattr(inventory_status, "oc_fetch_inventory_rows", empty_inventory)

    db = _FakeDb(
        [
            _FakeResult(one_or_none=SimpleNamespace(id=42)),
            _FakeResult(one=3),
            _FakeResult(one=4),
        ]
    )

    with pytest.raises(HTTPException) as exc:
        asyncio.run(inventory_status.execute_oc_sku_mappings_sync(db))

    assert exc.value.status_code == 502
    assert "preserving existing data" in exc.value.detail
    assert not db.committed
    assert not any(getattr(statement, "is_delete", False) for statement in db.statements)

