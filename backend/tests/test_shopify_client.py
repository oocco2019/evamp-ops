import httpx
import pytest

import app.services.shopify_client as shopify_client


@pytest.mark.asyncio
async def test_shopify_cursor_page_uses_only_cursor_safe_params(monkeypatch):
    requests = []

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, headers, params):
            requests.append(dict(params))
            request = httpx.Request("GET", url)
            if len(requests) == 1:
                return httpx.Response(
                    200,
                    json={"orders": [{"id": 1}]},
                    headers={
                        "link": (
                            '<https://example.myshopify.com/admin/api/2024-10/'
                            'orders.json?page_info=cursor-2>; rel="next"'
                        )
                    },
                    request=request,
                )
            return httpx.Response(200, json={"orders": [{"id": 2}]}, request=request)

    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", FakeAsyncClient)

    orders = await shopify_client.fetch_shopify_orders_paginated(
        "example",
        "shpat_test",
    )

    assert [order["id"] for order in orders] == [1, 2]
    assert requests[0]["status"] == "any"
    assert requests[1]["page_info"] == "cursor-2"
    assert requests[1]["limit"] == "250"
    assert "fields" in requests[1]
    assert "status" not in requests[1]
