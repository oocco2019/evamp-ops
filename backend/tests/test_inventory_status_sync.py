import pytest
from fastapi import HTTPException

import app.api.inventory_status as inventory_status
from app.models.settings import OCConnection


class _ConnectionResult:
    def scalar_one_or_none(self):
        return OCConnection(
            id=7,
            name="OC",
            region="UK",
            environment="stage",
            oauth_base_url="https://oauth.example.test",
            api_base_url="https://api.example.test",
        )


class _FakeDb:
    def __init__(self):
        self.execute_calls = 0
        self.committed = False

    async def execute(self, _stmt):
        self.execute_calls += 1
        return _ConnectionResult()

    async def commit(self):
        self.committed = True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("mapping_rows", "inventory_rows"),
    [
        (
            [],
            [
                {
                    "mfskuid": "MFS-1",
                    "service_region": "UK",
                    "available": 5,
                }
            ],
        ),
        (
            [
                {
                    "sku_code": "SKU-1",
                    "seller_skuid": "SELLER-1",
                    "reference_skuid": "REF-1",
                    "mfskuid": "MFS-1",
                }
            ],
            [],
        ),
        (
            [
                {
                    "sku_code": "",
                    "seller_skuid": "SELLER-1",
                    "reference_skuid": "REF-1",
                    "mfskuid": "",
                }
            ],
            [
                {
                    "mfskuid": "MFS-1",
                    "service_region": "UK",
                    "available": 5,
                }
            ],
        ),
    ],
)
async def test_oc_sku_sync_preserves_existing_rows_when_replacement_feed_is_empty(
    monkeypatch,
    mapping_rows,
    inventory_rows,
):
    async def fake_sync_sku_mappings(_db):
        return mapping_rows

    async def fake_fetch_inventory_rows(_db):
        return inventory_rows

    monkeypatch.setattr(inventory_status, "oc_sync_sku_mappings", fake_sync_sku_mappings)
    monkeypatch.setattr(inventory_status, "oc_fetch_inventory_rows", fake_fetch_inventory_rows)

    db = _FakeDb()

    with pytest.raises(HTTPException) as exc:
        await inventory_status.execute_oc_sku_mappings_sync(db)

    assert exc.value.status_code == 502
    assert "preserving existing" in exc.value.detail
    assert db.execute_calls == 1
    assert db.committed is False
