"""Shopify Payments fee application on parsed orders."""
from decimal import Decimal

from app.services.shopify_client import apply_shopify_payments_to_parsed


def test_apply_shopify_payments_reduces_due_seller_by_fees():
    parsed = {
        "total_due_seller": Decimal("133.32"),
        "total_due_seller_currency": "GBP",
        "order_currency": "GBP",
        "fee_total": None,
    }
    out = apply_shopify_payments_to_parsed(
        parsed,
        fee_total=Decimal("3.45"),
        net_charged=Decimal("159.99"),
    )
    assert out["fee_total"] == Decimal("3.45")
    assert out["total_due_seller"] == Decimal("156.54")  # 159.99 - 3.45


def test_apply_shopify_payments_full_refund_leaves_negative_fee_clawback():
    out = apply_shopify_payments_to_parsed(
        {"order_currency": "GBP"},
        fee_total=Decimal("3.45"),
        net_charged=Decimal("0"),  # sale reversed by refund
    )
    assert out["total_due_seller"] == Decimal("-3.45")
