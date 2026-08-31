"""Long-term recovery: parsers must retain the full raw marketplace order object.

See docs/DATA_RETENTION.md and .cursor/rules/data-retention.mdc. Platforms purge orders, so we
keep the complete payload (including line items) in orders.raw_payload.
"""
import pytest

from app.services.ebay_client import parse_orders_to_import
from app.services.shopify_client import fetch_shopify_orders_paginated, parse_shopify_order_to_import


def test_ebay_parse_retains_full_raw_order_object():
    raw_order = {
        "orderId": "12-34567-89012",
        "creationDate": "2026-01-15T10:00:00.000Z",
        "lastModifiedDate": "2026-01-16T10:00:00.000Z",
        "buyer": {"username": "someBuyer"},
        "pricingSummary": {"total": {"value": "19.99", "currency": "GBP"}},
        "lineItems": [
            {"lineItemId": "L1", "sku": "SKU-A", "quantity": 2,
             "some_field_we_do_not_map": "keepme"},
        ],
        "an_unmapped_top_level_field": {"nested": [1, 2, 3]},
    }
    parsed = parse_orders_to_import({"orders": [raw_order]})
    assert len(parsed) == 1
    rp = parsed[0]["raw_payload"]
    assert rp == raw_order
    # Unmapped data survives verbatim for future recovery.
    assert rp["an_unmapped_top_level_field"] == {"nested": [1, 2, 3]}
    assert rp["lineItems"][0]["some_field_we_do_not_map"] == "keepme"


def test_shopify_parse_retains_full_raw_order_object():
    raw_order = {
        "id": 5550001112223,
        "created_at": "2026-02-01T12:00:00+00:00",
        "updated_at": "2026-02-02T12:00:00+00:00",
        "currency": "GBP",
        "total_price": "29.99",
        "line_items": [{"sku": "SKU-B", "quantity": 1}],
        "an_unmapped_field": "keepme",
    }
    parsed = parse_shopify_order_to_import(raw_order)
    assert parsed["raw_payload"] == raw_order
    assert parsed["raw_payload"]["an_unmapped_field"] == "keepme"


@pytest.mark.asyncio
async def test_shopify_fetch_does_not_request_field_limited_orders(monkeypatch):
    """Shopify raw_payload retention depends on fetching unmapped fields, not a sparse projection."""
    captured_params = []

    class FakeResponse:
        def __init__(self, orders, link=""):
            self._orders = orders
            self.headers = {"link": link}

        def raise_for_status(self):
            return None

        def json(self):
            return {"orders": self._orders}

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            self._call_count = 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            captured_params.append(dict(params))
            self._call_count += 1
            if self._call_count == 1:
                return FakeResponse(
                    [{"id": 1, "an_unmapped_field": "kept"}],
                    '<https://shop.myshopify.com/admin/api/2024-10/orders.json?page_info=next-token>; rel="next"',
                )
            return FakeResponse([{"id": 2, "another_unmapped_field": "kept-too"}])

    monkeypatch.setattr("app.services.shopify_client.httpx.AsyncClient", FakeAsyncClient)

    orders = await fetch_shopify_orders_paginated("shop", "token")

    assert orders == [
        {"id": 1, "an_unmapped_field": "kept"},
        {"id": 2, "another_unmapped_field": "kept-too"},
    ]
    assert captured_params == [
        {"status": "any", "limit": "250"},
        {"limit": "250", "page_info": "next-token"},
    ]
