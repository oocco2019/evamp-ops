"""Long-term recovery: parsers must retain the full raw marketplace order object.

See docs/DATA_RETENTION.md and .cursor/rules/data-retention.mdc. Platforms purge orders, so we
keep the complete payload (including line items) in orders.raw_payload.
"""
import asyncio
from datetime import datetime

from app.services.ebay_client import parse_orders_to_import
from app.services import shopify_client
from app.services.shopify_client import parse_shopify_order_to_import


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


def test_shopify_fetch_does_not_field_filter_raw_order_payload(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, orders, link=""):
            self._orders = orders
            self.headers = {"link": link}

        def raise_for_status(self):
            return None

        def json(self):
            return {"orders": self._orders}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            calls.append(params.copy())
            if len(calls) == 1:
                return FakeResponse(
                    [{"id": 1, "line_items": [], "unmapped_shopify_field": "keepme"}],
                    '<https://test-shop.myshopify.com/admin/api/2024-10/orders.json?page_info=next>; rel="next"',
                )
            return FakeResponse([{"id": 2, "line_items": [], "another_unmapped_field": "keepme"}])

    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", FakeAsyncClient)

    orders = asyncio.run(
        shopify_client.fetch_shopify_orders_paginated(
            "test-shop",
            "token",
            created_at_min=datetime(2026, 1, 1),
        )
    )

    assert len(orders) == 2
    assert orders[0]["unmapped_shopify_field"] == "keepme"
    assert orders[1]["another_unmapped_field"] == "keepme"
    assert calls
    assert all("fields" not in params for params in calls)
