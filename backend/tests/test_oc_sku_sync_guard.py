from app.api.inventory_status import _empty_oc_sku_snapshot_would_wipe_existing


def test_empty_oc_sku_snapshot_guard_blocks_wiping_existing_rows():
    assert _empty_oc_sku_snapshot_would_wipe_existing([], [], 5, 5) is True
    assert _empty_oc_sku_snapshot_would_wipe_existing([], [{"mfskuid": "1"}], 5, 5) is True
    assert _empty_oc_sku_snapshot_would_wipe_existing([{"mfskuid": "1"}], [], 5, 5) is True


def test_empty_oc_sku_snapshot_guard_allows_initial_empty_sync():
    assert _empty_oc_sku_snapshot_would_wipe_existing([], [], 0, 0) is False


def test_empty_oc_sku_snapshot_guard_allows_non_empty_replacement():
    assert _empty_oc_sku_snapshot_would_wipe_existing(
        [{"sku_code": "SKU-1", "mfskuid": "MF-1"}],
        [{"mfskuid": "MF-1"}],
        5,
        5,
    ) is False
