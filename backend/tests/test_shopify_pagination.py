import asyncio

from app.services import shopify_client


def test_fetch_shopify_orders_page_info_request_does_not_resend_filters(monkeypatch):
    calls = []

    class FakeResponse:
        def __init__(self, orders, link=""):
            self._orders = orders
            self.headers = {"link": link}

        def raise_for_status(self):
            return None

        def json(self):
            return {"orders": self._orders}

    class FakeClient:
        def __init__(self, timeout):
            self._responses = [
                FakeResponse(
                    [{"id": 1}],
                    '<https://example.myshopify.com/admin/api/2024-10/orders.json?page_info=cursor-2>; rel="next"',
                ),
                FakeResponse([{"id": 2}]),
            ]

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, url, headers, params):
            calls.append(dict(params))
            return self._responses.pop(0)

    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", FakeClient)

    orders = asyncio.run(
        shopify_client.fetch_shopify_orders_paginated(
            "example.myshopify.com",
            "token",
        )
    )

    assert [o["id"] for o in orders] == [1, 2]
    assert calls[0]["status"] == "any"
    assert calls[0]["fields"]
    assert calls[1] == {"limit": "250", "page_info": "cursor-2"}
