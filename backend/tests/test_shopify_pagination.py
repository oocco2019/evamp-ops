import asyncio

from app.services import shopify_client


class _FakeResponse:
    def __init__(self, orders, link=""):
        self._orders = orders
        self.headers = {"link": link} if link else {}

    def json(self):
        return {"orders": self._orders}

    def raise_for_status(self):
        return None


def test_next_page_url_extracts_next_link():
    link = (
        '<https://demo.myshopify.com/admin/api/2024-10/orders.json?page_info=NEXT&limit=250>; rel="next", '
        '<https://demo.myshopify.com/admin/api/2024-10/orders.json?page_info=PREV&limit=250>; rel="previous"'
    )

    assert shopify_client._next_page_url(link) == (
        "https://demo.myshopify.com/admin/api/2024-10/orders.json?page_info=NEXT&limit=250"
    )


def test_fetch_shopify_orders_uses_next_link_without_readding_filters(monkeypatch):
    calls = []
    next_url = "https://demo.myshopify.com/admin/api/2024-10/orders.json?page_info=NEXT&limit=250"
    link = f"<{next_url}>; rel=\"next\""
    responses = [
        _FakeResponse([{"id": 1}], link=link),
        _FakeResponse([{"id": 2}]),
    ]

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url, *, headers=None, params=None):
            calls.append({"url": url, "params": params})
            return responses[len(calls) - 1]

    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", FakeAsyncClient)

    orders = asyncio.run(
        shopify_client.fetch_shopify_orders_paginated(
            "demo.myshopify.com",
            "shpat_token",
        )
    )

    assert orders == [{"id": 1}, {"id": 2}]
    assert calls[0]["params"]["status"] == "any"
    assert "fields" in calls[0]["params"]
    assert calls[1] == {"url": next_url, "params": None}
