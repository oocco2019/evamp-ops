import asyncio
from datetime import datetime

import httpx

from app.services import shopify_client
from app.services.shopify_client import fetch_shopify_orders_paginated


def test_fetch_shopify_orders_paginated_uses_cursor_safe_params(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(
                200,
                json={"orders": [{"id": 1}]},
                headers={
                    "Link": '<https://store.myshopify.com/admin/api/2024-10/orders.json?page_info=NEXTTOKEN>; rel="next"'
                },
            )
        return httpx.Response(200, json={"orders": [{"id": 2}]})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            self._client = original_async_client(transport=transport)

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, exc_type, exc, tb):
            await self._client.aclose()

    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", MockAsyncClient)

    orders = asyncio.run(
        fetch_shopify_orders_paginated(
            "store",
            "token",
            created_at_min=datetime(2026, 1, 1, 12, 0, 0),
        )
    )

    assert [o["id"] for o in orders] == [1, 2]
    first_params = requests[0].url.params
    assert first_params["status"] == "any"
    assert first_params["created_at_min"] == "2026-01-01T12:00:00Z"
    assert first_params["order"] == "created_at asc"

    cursor_params = requests[1].url.params
    assert cursor_params["page_info"] == "NEXTTOKEN"
    assert "status" not in cursor_params
    assert "created_at_min" not in cursor_params
    assert "order" not in cursor_params


def test_fetch_shopify_orders_paginated_orders_updated_at_filter(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"orders": []})

    transport = httpx.MockTransport(handler)
    original_async_client = httpx.AsyncClient

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            self._client = original_async_client(transport=transport)

        async def __aenter__(self):
            return self._client

        async def __aexit__(self, exc_type, exc, tb):
            await self._client.aclose()

    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", MockAsyncClient)

    asyncio.run(
        fetch_shopify_orders_paginated(
            "store",
            "token",
            updated_at_min=datetime(2026, 1, 2, 3, 4, 5),
        )
    )

    params = requests[0].url.params
    assert params["updated_at_min"] == "2026-01-02T03:04:05Z"
    assert params["order"] == "updated_at asc"
