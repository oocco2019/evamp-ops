"""Long-term recovery: parsers must retain the full raw marketplace order object.

See docs/DATA_RETENTION.md and .cursor/rules/data-retention.mdc. Platforms purge orders, so we
keep the complete payload (including line items) in orders.raw_payload.
"""
from app.services.ebay_client import parse_orders_to_import
from app.services.shopify_client import parse_shopify_order_to_import
from app.api.stock import _retain_fetched_order_raw_payload


def test_ebay_parse_retains_full_raw_order_object():
    raw_order = {
        "orderId": "12-34567-89012",
        "creationDate": "2026-01-15T10:00:00.000Z",
        "lastModifiedDate": "2026-01-16T10:00:00.000Z",
        "buyer": {"username": "someBuyer"},
        "pricingSummary": {"total": {"value": "19.99", "currency": "GBP"}},
        "lineItems": [
            {"lineItemId": "L1", "sku": "SKU-A", "quantity": 2,
             "some_field_we_do_not_map": "keepme"},
        ],
        "an_unmapped_top_level_field": {"nested": [1, 2, 3]},
    }
    parsed = parse_orders_to_import({"orders": [raw_order]})
    assert len(parsed) == 1
    rp = parsed[0]["raw_payload"]
    assert rp == raw_order
    # Unmapped data survives verbatim for future recovery.
    assert rp["an_unmapped_top_level_field"] == {"nested": [1, 2, 3]}
    assert rp["lineItems"][0]["some_field_we_do_not_map"] == "keepme"


def test_shopify_parse_retains_full_raw_order_object():
    raw_order = {
        "id": 5550001112223,
        "created_at": "2026-02-01T12:00:00+00:00",
        "updated_at": "2026-02-02T12:00:00+00:00",
        "currency": "GBP",
        "total_price": "29.99",
        "line_items": [{"sku": "SKU-B", "quantity": 1}],
        "an_unmapped_field": "keepme",
    }
    parsed = parse_shopify_order_to_import(raw_order)
    assert parsed["raw_payload"] == raw_order
    assert parsed["raw_payload"]["an_unmapped_field"] == "keepme"


def test_get_order_fallback_retains_raw_payload_when_missing():
    order = type("OrderStub", (), {"raw_payload": None})()
    raw_order = {
        "orderId": "12-34567-89012",
        "paymentSummary": {"totalDueSeller": {"value": "19.99", "currency": "GBP"}},
        "lineItems": [{"lineItemId": "L1", "sku": "SKU-A", "quantity": 1}],
        "unmapped_field": {"keep": True},
    }

    _retain_fetched_order_raw_payload(order, raw_order)

    assert order.raw_payload == raw_order
    assert order.raw_payload["unmapped_field"] == {"keep": True}


def test_get_order_fallback_does_not_overwrite_existing_raw_payload():
    existing = {"orderId": "existing"}
    order = type("OrderStub", (), {"raw_payload": existing})()

    _retain_fetched_order_raw_payload(order, {"orderId": "new"})

    assert order.raw_payload == existing
