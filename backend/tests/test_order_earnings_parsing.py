"""
Unit tests for order earnings (totalDueSeller) parsing.
Verifies we match eBay Order earnings in GBP: 74.02, 54.15, 101.95 for the given orders.
Run from backend: pytest tests/test_order_earnings_parsing.py -v
"""
import pytest
from decimal import Decimal

from app.services.ebay_client import (
    _parse_total_due_seller,
    _parse_amount,
    parse_orders_to_import,
)


# Expected Order earnings (GBP) from eBay UI for user's test orders
EXPECTED_EARNINGS = {
    "02-14199-08090": ("74.02", "GBP"),
    "11-14176-11233": ("54.15", "GBP"),
    "22-14137-74658": ("101.95", "GBP"),
}


def test_parse_total_due_seller_gbp_as_main_currency():
    """When API returns value/currency in GBP, we use it."""
    amount = {"value": "54.15", "currency": "GBP"}
    val, cc = _parse_total_due_seller(amount)
    assert val == Decimal("54.15")
    assert cc == "GBP"


def test_parse_total_due_seller_gbp_as_converted():
    """When API returns order currency as main and GBP in convertedFrom, we prefer GBP."""
    amount = {
        "value": "63.20",
        "currency": "EUR",
        "convertedFromValue": "54.15",
        "convertedFromCurrency": "GBP",
    }
    val, cc = _parse_total_due_seller(amount)
    assert val == Decimal("54.15")
    assert cc == "GBP"


def test_parse_total_due_seller_expected_order_11():
    """11-14176-11233: Order earnings £54.15."""
    amount_gbp_main = {"value": "54.15", "currency": "GBP"}
    val, cc = _parse_total_due_seller(amount_gbp_main)
    assert val == Decimal("54.15"), "expected 54.15 when GBP is main"
    assert cc == "GBP"

    amount_eur_with_gbp_converted = {
        "value": "64.50",
        "currency": "EUR",
        "convertedFromValue": "54.15",
        "convertedFromCurrency": "GBP",
    }
    val2, cc2 = _parse_total_due_seller(amount_eur_with_gbp_converted)
    assert val2 == Decimal("54.15"), "expected 54.15 when GBP is in convertedFrom"
    assert cc2 == "GBP"


def test_parse_total_due_seller_expected_all_three():
    """All three orders: 74.02, 54.15, 101.95 GBP."""
    for order_id, (expected_val, expected_cc) in EXPECTED_EARNINGS.items():
        amount = {"value": expected_val, "currency": expected_cc}
        val, cc = _parse_total_due_seller(amount)
        assert val == Decimal(expected_val), f"order {order_id} value"
        assert cc == expected_cc, f"order {order_id} currency"


def test_parse_orders_to_import_extracts_order_earnings():
    """parse_orders_to_import sets total_due_seller from paymentSummary.totalDueSeller (GBP preferred)."""
    api_response = {
        "orders": [
            {
                "orderId": "11-14176-11233",
                "creationDate": "2025-01-15T10:00:00.000Z",
                "lastModifiedDate": "2025-01-15T10:00:00.000Z",
                "fulfillmentStartInstructions": [{"shippingStep": {"shipTo": {"contactAddress": {"countryCode": "DE"}}}}],
                "buyer": {"username": "buyer1"},
                "cancelStatus": {"cancelState": "NONE_REQUESTED"},
                "pricingSummary": {"total": {"value": "70.00", "currency": "EUR"}},
                "paymentSummary": {
                    "totalDueSeller": {
                        "value": "64.50",
                        "currency": "EUR",
                        "convertedFromValue": "54.15",
                        "convertedFromCurrency": "GBP",
                    }
                },
                "lineItems": [
                    {"lineItemId": "1", "sku": "SKU1", "quantity": 1},
                ],
            },
            {
                "orderId": "02-14199-08090",
                "creationDate": "2025-01-16T10:00:00.000Z",
                "lastModifiedDate": "2025-01-16T10:00:00.000Z",
                "fulfillmentStartInstructions": [{"shippingStep": {"shipTo": {"contactAddress": {"countryCode": "DE"}}}}],
                "buyer": {},
                "cancelStatus": {"cancelState": "NONE_REQUESTED"},
                "pricingSummary": {},
                "paymentSummary": {
                    "totalDueSeller": {"value": "74.02", "currency": "GBP"},
                },
                "lineItems": [{"lineItemId": "1", "sku": "SKU2", "quantity": 1}],
            },
            {
                "orderId": "22-14137-74658",
                "creationDate": "2025-01-17T10:00:00.000Z",
                "lastModifiedDate": "2025-01-17T10:00:00.000Z",
                "fulfillmentStartInstructions": [{"shippingStep": {"shipTo": {"contactAddress": {"countryCode": "DE"}}}}],
                "buyer": {},
                "cancelStatus": {"cancelState": "NONE_REQUESTED"},
                "pricingSummary": {},
                "paymentSummary": {
                    "totalDueSeller": {"value": "101.95", "currency": "GBP"},
                },
                "lineItems": [{"lineItemId": "1", "sku": "SKU3", "quantity": 1}],
            },
        ],
    }
    parsed = parse_orders_to_import(api_response)
    by_id = {o["ebay_order_id"]: o for o in parsed}
    assert by_id["11-14176-11233"]["total_due_seller"] == Decimal("54.15")
    assert by_id["11-14176-11233"]["total_due_seller_currency"] == "GBP"
    assert by_id["02-14199-08090"]["total_due_seller"] == Decimal("74.02")
    assert by_id["02-14199-08090"]["total_due_seller_currency"] == "GBP"
    assert by_id["22-14137-74658"]["total_due_seller"] == Decimal("101.95")
    assert by_id["22-14137-74658"]["total_due_seller_currency"] == "GBP"
