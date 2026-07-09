"""Long-term recovery: parsers must retain the full raw marketplace order object.

See docs/DATA_RETENTION.md and .cursor/rules/data-retention.mdc. Platforms purge orders, so we
keep the complete payload (including line items) in orders.raw_payload.
"""
from app.services.ebay_client import parse_orders_to_import
from app.services.oc_client import _merge_inbound_list_and_detail
from app.services.shopify_client import parse_shopify_order_to_import


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


def test_inbound_detail_merge_does_not_erase_non_empty_list_payloads():
    list_raw = {
        "inboundOrderNo": "OC-123",
        "trackingList": [{"trackingNo": "TRACK-1"}],
        "SKUList": [{"sku": "SKU-A", "qty": 2}],
        "files": {"invoice": "keep.pdf"},
    }
    detail = {
        "trackingList": [],
        "SKUList": [],
        "files": {},
        "status": "Put away",
    }

    merged = _merge_inbound_list_and_detail(list_raw, detail)

    assert merged["trackingList"] == [{"trackingNo": "TRACK-1"}]
    assert merged["SKUList"] == [{"sku": "SKU-A", "qty": 2}]
    assert merged["files"] == {"invoice": "keep.pdf"}
    assert merged["status"] == "Put away"


def test_inbound_detail_merge_keeps_empty_collection_when_no_existing_payload():
    merged = _merge_inbound_list_and_detail({"inboundOrderNo": "OC-123"}, {"trackingList": []})

    assert merged["trackingList"] == []
