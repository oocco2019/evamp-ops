"""Unit tests for OC stock movement persistence helpers."""
from datetime import datetime

import pytest

from app.services.oc_stock_movement_store import max_movement_update_time_utc


class _ScalarResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _CaptureDb:
    def __init__(self):
        self.statement = None

    async def execute(self, statement):
        self.statement = statement
        return _ScalarResult(datetime(2026, 4, 10, 12, 0))


@pytest.mark.asyncio
async def test_max_movement_watermark_uses_created_at_for_unparsed_update_times():
    db = _CaptureDb()

    result = await max_movement_update_time_utc(db, 1)

    assert result == datetime(2026, 4, 10, 12, 0)
    compiled = str(db.statement.compile(compile_kwargs={"literal_binds": True})).lower()
    assert "max(coalesce(" in compiled
    assert "update_time_utc" in compiled
    assert "created_at" in compiled
