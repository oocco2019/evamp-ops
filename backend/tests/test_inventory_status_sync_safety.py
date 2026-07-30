import pytest
from fastapi import HTTPException

from app.api import inventory_status
from app.models.settings import OCConnection, OCInboundOrder
from app.services import oc_client
from app.services.oc_client import OCAPIError


class _ScalarList:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, *, scalar=None, scalars=None, first=None):
        self._scalar = scalar
        self._scalars = scalars or []
        self._first = first

    def scalar_one_or_none(self):
        return self._scalar

    def scalars(self):
        return _ScalarList(self._scalars)

    def first(self):
        return self._first


class _SequencedSession:
    def __init__(self, results):
        self._results = list(results)
        self.added = []
        self.committed = False

    async def execute(self, statement):
        if not self._results:
            raise AssertionError(f"Unexpected execute call: {statement}")
        return self._results.pop(0)

    def add(self, row):
        self.added.append(row)

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
async def test_inbound_upsert_does_not_crash_on_ambiguous_identifier_fallback():
    first_match = OCInboundOrder(
        id=1,
        connection_id=7,
        dedup_key="::seller-1",
        seller_inbound_number="seller-1",
    )
    second_match = OCInboundOrder(
        id=2,
        connection_id=7,
        dedup_key="oc-1::seller-2",
        seller_inbound_number="seller-2",
        oc_inbound_number="oc-1",
    )
    db = _SequencedSession(
        [
            _Result(scalar=None),  # no exact dedup_key row
            _Result(scalars=[]),  # no exact same-row identifier match
            _Result(scalars=[first_match, second_match]),  # loose OR match is ambiguous
        ]
    )

    processed = await inventory_status._upsert_inbound_rows(
        db,
        7,
        [
            {
                "seller_inbound_number": "seller-1",
                "oc_inbound_number": "oc-1",
                "status": "In transit",
            }
        ],
    )

    assert processed == 1
    assert len(db.added) == 1
    assert db.added[0].dedup_key == "oc-1::seller-1"
    assert first_match.dedup_key == "::seller-1"
    assert second_match.dedup_key == "oc-1::seller-2"


@pytest.mark.asyncio
async def test_sku_sync_preserves_existing_mappings_when_replacement_is_empty(monkeypatch):
    async def empty_mappings(db):
        return []

    async def nonempty_inventory(db):
        return [{"mfskuid": "MF-1", "service_region": "UK", "available": 3}]

    monkeypatch.setattr(inventory_status, "oc_sync_sku_mappings", empty_mappings)
    monkeypatch.setattr(inventory_status, "oc_fetch_inventory_rows", nonempty_inventory)

    connection = OCConnection(
        id=7,
        name="OC",
        region="UK",
        environment="stage",
        oauth_base_url="https://oauth.example",
        api_base_url="https://api.example",
        is_active=True,
    )
    db = _SequencedSession(
        [
            _Result(scalar=connection),
            _Result(first=(123,)),  # existing mapping cache would be deleted without the guard
            _Result(first=None),
        ]
    )

    with pytest.raises(HTTPException) as exc:
        await inventory_status.execute_oc_sku_mappings_sync(db)

    assert exc.value.status_code == 502
    assert "preserved existing cached mappings" in exc.value.detail
    assert db.added == []
    assert db.committed is False


@pytest.mark.asyncio
async def test_stock_snapshot_vendor_error_raises(monkeypatch):
    async def fake_call_oc(db, conn, method, endpoint, *, body_obj=None):
        return {"success": False, "errors": [{"message": "rate limited"}]}

    monkeypatch.setattr(oc_client, "_call_oc", fake_call_oc)
    conn = OCConnection(
        id=7,
        name="OC",
        region="UK",
        environment="stage",
        oauth_base_url="https://oauth.example",
        api_base_url="https://api.example",
        is_active=True,
    )

    with pytest.raises(OCAPIError, match="StockSnapshot: rate limited"):
        await oc_client._fetch_snapshot_rows(None, conn, ["UK"])
