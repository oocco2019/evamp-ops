import asyncio
from datetime import date, datetime
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import inventory_status
from app.services import oc_client


def test_oc_fetch_inbound_orders_paginates_each_chunk(monkeypatch):
    calls = []

    async def fake_get_active_connection(db):
        return SimpleNamespace(id=1)

    def make_order(n: int):
        return {
            "referenceNumber": f"SELLER-{n}",
            "inboundOrderNumber": f"OC-{n}",
            "warehouseCode": "UK-ABC",
            "status": "Put away",
            "skuQty": 1,
            "putAwayQty": 1,
        }

    async def fake_call_oc(db, conn, method, endpoint_path, body_obj=None):
        data = dict((body_obj or {}).get("data") or {})
        calls.append(data)
        assert endpoint_path == "/openapi/3pp/inbound/v1/query"
        assert "page" in data
        page_no = data["page"]
        if page_no == 1:
            rows = [make_order(1), make_order(2)]
        elif page_no == 2:
            rows = [make_order(3)]
        else:
            rows = []
        return {"data": {"inboundOrderList": rows}}

    async def noop(*args, **kwargs):
        return None

    monkeypatch.setattr(oc_client, "_get_active_connection", fake_get_active_connection)
    monkeypatch.setattr(oc_client, "_call_oc", fake_call_oc)
    monkeypatch.setattr(oc_client, "_merge_inbound_detail_into_rows", noop)
    monkeypatch.setattr(oc_client, "_merge_inbound_detail_by_seller_numbers", noop)
    monkeypatch.setattr(oc_client, "_merge_inbound_label_query_into_rows", noop)

    rows = asyncio.run(
        oc_client.oc_fetch_inbound_orders(
            db=None,
            page_size=2,
            date_from=date(2026, 1, 1),
            date_to=datetime(2026, 1, 1, 23, 59, 59),
        )
    )

    assert [row["oc_inbound_number"] for row in rows] == ["OC-1", "OC-2", "OC-3"]
    assert [call["page"] for call in calls] == [1, 2]


def test_empty_oc_sku_sync_preserves_existing_rows(monkeypatch):
    class FakeResult:
        def __init__(self, *, scalar_value=None, scalar_one=None):
            self._scalar_value = scalar_value
            self._scalar_one = scalar_one

        def scalar_one_or_none(self):
            return self._scalar_one

        def scalar(self):
            return self._scalar_value

    class FakeDB:
        def __init__(self):
            self.calls = 0
            self.delete_called = False
            self.committed = False

        async def execute(self, statement):
            if statement.__class__.__name__ == "Delete":
                self.delete_called = True
            self.calls += 1
            if self.calls == 1:
                return FakeResult(scalar_one=SimpleNamespace(id=7))
            return FakeResult(scalar_value=1)

        async def commit(self):
            self.committed = True

    async def empty_sku_mappings(db):
        return []

    async def empty_inventory_rows(db):
        return []

    fake_db = FakeDB()
    monkeypatch.setattr(inventory_status, "oc_sync_sku_mappings", empty_sku_mappings)
    monkeypatch.setattr(inventory_status, "oc_fetch_inventory_rows", empty_inventory_rows)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(inventory_status.execute_oc_sku_mappings_sync(fake_db))

    assert exc.value.status_code == 502
    assert fake_db.delete_called is False
    assert fake_db.committed is False
