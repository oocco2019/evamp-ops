"""Long-term recovery: parsers must retain the full raw marketplace order object.

See docs/DATA_RETENTION.md and .cursor/rules/data-retention.mdc. Platforms purge orders, so we
keep the complete payload (including line items) in orders.raw_payload.
"""
import asyncio
import datetime

from app.services.ebay_client import parse_orders_to_import
from app.services import shopify_client
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


def test_shopify_fetch_does_not_request_truncated_fields(monkeypatch):
    class FakeResponse:
        def __init__(self, payload, link=""):
            self._payload = payload
            self.headers = {"link": link}

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeAsyncClient:
        requests = []

        def __init__(self, timeout):
            self._responses = [
                FakeResponse(
                    {"orders": [{"id": 1, "customer": {"id": 1001}}]},
                    '<https://example.myshopify.com/admin/api/2024-10/orders.json?page_info=next-page>; rel="next"',
                ),
                FakeResponse({"orders": [{"id": 2, "refunds": [{"id": 2002}]}]}),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            self.requests.append(dict(params))
            return self._responses.pop(0)

    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", FakeAsyncClient)

    orders = asyncio.run(
        fetch_shopify_orders_paginated(
            "example",
            "token",
            created_at_min=datetime.datetime(2026, 1, 1, 0, 0, 0),
        )
    )

    assert orders == [
        {"id": 1, "customer": {"id": 1001}},
        {"id": 2, "refunds": [{"id": 2002}]},
    ]
    assert len(FakeAsyncClient.requests) == 2
    assert all("fields" not in params for params in FakeAsyncClient.requests)
