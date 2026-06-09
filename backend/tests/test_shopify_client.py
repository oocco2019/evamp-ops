from datetime import datetime

import pytest

from app.services import shopify_client


class _FakeShopifyResponse:
    def __init__(self, orders, link=""):
        self._orders = orders
        self.headers = {"link": link}

    def raise_for_status(self):
        return None

    def json(self):
        return {"orders": self._orders}


@pytest.mark.asyncio
async def test_fetch_shopify_orders_paginated_cursor_request_omits_status(monkeypatch):
    calls = []

    class FakeAsyncClient:
        def __init__(self, timeout):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            calls.append(dict(params))
            if len(calls) == 1:
                return _FakeShopifyResponse(
                    [{"id": 1}],
                    '<https://demo.myshopify.com/admin/api/2024-10/orders.json?page_info=next-token>; rel="next"',
                )
            return _FakeShopifyResponse([{"id": 2}])

    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", FakeAsyncClient)

    rows = await shopify_client.fetch_shopify_orders_paginated(
        "demo",
        "token",
        created_at_min=datetime(2026, 1, 1),
    )

    assert [r["id"] for r in rows] == [1, 2]
    assert calls[0]["status"] == "any"
    assert calls[0]["created_at_min"] == "2026-01-01T00:00:00Z"
    assert calls[1]["page_info"] == "next-token"
    assert "status" not in calls[1]
    assert "created_at_min" not in calls[1]
