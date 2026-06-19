"""Tests for Shopify order normalization into the shared profit pipeline."""
from decimal import Decimal

from app.api.stock import _order_profit_gbp
from app.services.shopify_client import parse_shopify_order_to_import


def _shopify_order(country_code: str) -> dict:
    return {
        "id": 123456,
        "name": "#1001",
        "created_at": "2026-01-15T10:00:00Z",
        "updated_at": "2026-01-15T10:05:00Z",
        "currency": "GBP",
        "current_total_price": "120.00",
        "current_total_tax": "20.00",
        "current_subtotal_price": "120.00",
        "shipping_address": {"country_code": country_code},
        "line_items": [
            {
                "id": 987,
                "sku": "SKU-1",
                "quantity": 1,
                "price": "120.00",
                "pre_tax_price": "100.00",
                "tax_lines": [{"price": "20.00"}],
            }
        ],
    }


def test_shopify_uk_payout_stays_vat_inclusive_for_profit_engine():
    parsed = parse_shopify_order_to_import(_shopify_order("GB"))

    assert parsed["country"] == "GB"
    assert parsed["total_due_seller"] == Decimal("120.00")
    gross = _order_profit_gbp(
        parsed["total_due_seller"],
        parsed["total_due_seller_currency"],
        parsed["price_total"],
        parsed["tax_total"],
        parsed["order_currency"],
        parsed["country"],
        line_cost_usd_total=Decimal("0"),
        line_postage_usd_total=Decimal("0"),
        usd_to_gbp=1.0,
    )
    assert gross == Decimal("100.00")


def test_shopify_non_uk_payout_remains_tax_exclusive_proxy():
    parsed = parse_shopify_order_to_import(_shopify_order("US"))

    assert parsed["country"] == "US"
    assert parsed["total_due_seller"] == Decimal("100.00")
