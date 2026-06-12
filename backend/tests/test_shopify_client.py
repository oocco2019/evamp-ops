"""Tests for Shopify REST client request construction."""

from app.services.shopify_client import _orders_page_params


def test_orders_page_params_drop_filter_params_after_cursor():
    first_params = {
        "status": "any",
        "limit": "250",
        "fields": "id,name",
        "updated_at_min": "2026-01-01T00:00:00Z",
    }

    params = _orders_page_params("cursor-token", first_params, "id,name")

    assert params == {
        "limit": "250",
        "page_info": "cursor-token",
        "fields": "id,name",
    }


def test_orders_page_params_keep_initial_filters_on_first_page():
    first_params = {
        "status": "any",
        "limit": "250",
        "fields": "id,name",
        "created_at_min": "2026-01-01T00:00:00Z",
    }

    assert _orders_page_params(None, first_params, "id,name") is first_params
