"""Shopify Payments fee application on parsed orders."""
from decimal import Decimal

from app.services.shopify_client import (
    apply_shopify_payments_to_parsed,
    settlement_from_order_transactions,
)


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


def test_settlement_none_when_no_success_sale_capture_refund():
    """Empty / non-settlement txs must not become (0, 0) and wipe REST payout."""
    assert settlement_from_order_transactions(None) is None
    assert settlement_from_order_transactions([]) is None
    assert (
        settlement_from_order_transactions(
            [{"kind": "AUTHORIZATION", "status": "SUCCESS", "amountSet": {"shopMoney": {"amount": "10"}}}]
        )
        is None
    )
    assert (
        settlement_from_order_transactions(
            [{"kind": "SALE", "status": "PENDING", "amountSet": {"shopMoney": {"amount": "10"}}}]
        )
        is None
    )


def test_settlement_nets_sale_minus_refund_and_fees():
    txs = [
        {
            "kind": "SALE",
            "status": "SUCCESS",
            "amountSet": {"shopMoney": {"amount": "100.00"}},
            "fees": [{"amount": {"amount": "2.50"}}],
        },
        {
            "kind": "REFUND",
            "status": "SUCCESS",
            "amountSet": {"shopMoney": {"amount": "20.00"}},
            "fees": [],
        },
    ]
    assert settlement_from_order_transactions(txs) == (Decimal("2.50"), Decimal("80.00"))
