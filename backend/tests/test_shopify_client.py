"""Unit tests for Shopify Admin API pagination helpers."""

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


class _FakeAsyncClient:
    requests = []

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers, params):
        self.requests.append({"url": url, "headers": headers, "params": dict(params)})
        if len(self.requests) == 1:
            return _FakeShopifyResponse(
                [{"id": 1}],
                '<https://example.myshopify.com/admin/api/2024-10/orders.json?page_info=cursor%3D&limit=250>; rel="next"',
            )
        return _FakeShopifyResponse([{"id": 2}])


@pytest.mark.asyncio
async def test_fetch_shopify_orders_uses_only_cursor_params_after_first_page(monkeypatch):
    _FakeAsyncClient.requests = []
    monkeypatch.setattr(shopify_client.httpx, "AsyncClient", _FakeAsyncClient)

    orders = await shopify_client.fetch_shopify_orders_paginated(
        "example.myshopify.com",
        "token",
        created_at_min=shopify_client.datetime(2026, 1, 1),
    )

    assert orders == [{"id": 1}, {"id": 2}]
    first_params = _FakeAsyncClient.requests[0]["params"]
    second_params = _FakeAsyncClient.requests[1]["params"]

    assert first_params["status"] == "any"
    assert "created_at_min" in first_params
    assert second_params["page_info"] == "cursor="
    assert second_params["limit"] == "250"
    assert "fields" in second_params
    assert "status" not in second_params
    assert "created_at_min" not in second_params
