import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from xml.etree.ElementTree import Element, SubElement, fromstring, tostring

import httpx
import pytest

from app.api.listing_video import _extract_item_id, _parse_item_ids, _run_job_worker
from app.services.ebay_client import (
    _et_child,
    _et_text,
    trading_remove_video_xml,
)


def test_parse_item_ids_lines_commas_and_urls():
    text = """
    136528644539
    https://www.ebay.co.uk/itm/135094023963
    136528644539
    111111111111, 222222222222
    """
    ids = _parse_item_ids(text)
    assert ids == ["136528644539", "135094023963", "111111111111", "222222222222"]


def test_extract_item_id_rejects_short():
    assert _extract_item_id("12345") is None
    assert _extract_item_id("136528644539") == "136528644539"


def test_remove_video_xml_uses_deleted_field():
    xml = trading_remove_video_xml("136528644539")
    assert "<DeletedField>Item.VideoDetails</DeletedField>" in xml
    assert "<ItemID>136528644539</ItemID>" in xml
    assert "VideoID" not in xml


def test_et_child_reads_leaf_sku_despite_falsy_element():
    """ElementTree leaf nodes with only text are falsy; ``find() or find()`` must not be used."""
    NS = "urn:ebay:apis:eBLBaseComponents"
    item = Element(f"{{{NS}}}Item")
    sku_el = SubElement(item, f"{{{NS}}}SKU")
    sku_el.text = "uke01"
    title_el = SubElement(item, f"{{{NS}}}Title")
    title_el.text = "KIA SPORTAGE PHEV cable"
    assert bool(sku_el) is False
    assert (item.find(f"{{{NS}}}SKU") or item.find("SKU")) is None
    assert _et_child(item, "SKU") is sku_el
    assert _et_text(item, "SKU") == "uke01"
    assert _et_text(item, "Title") == "KIA SPORTAGE PHEV cable"
    assert tostring(item).decode()  # keep tree valid


# ---------------------------------------------------------------------------
# Job worker unit tests (monkeypatched eBay calls)
# ---------------------------------------------------------------------------

def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_job(job_id: str, mode: str = "item_ids", sku: str | None = None):
    """Return a minimal ListingVideoJob-like object."""
    from app.models.listing_video import ListingVideoJob
    job = MagicMock(spec=ListingVideoJob)
    job.job_id = job_id
    job.mode = mode
    job.sku = sku
    job.video_id = "vid123"
    job.marketplace_id = None
    return job


def _make_item(job_id: str, item_id: str, status: str = "pending", attempt_count: int = 0):
    from app.models.listing_video import ListingVideoJobItem
    item = MagicMock(spec=ListingVideoJobItem)
    item.job_id = job_id
    item.item_id = item_id
    item.status = status
    item.attempt_count = attempt_count
    item.last_error = None
    return item


class _FakeSession:
    """Minimal async context manager + session stub used in DB patches."""
    def __init__(self):
        self.added = []
        self.executed = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        pass

    async def commit(self):
        pass

    async def get(self, model, pk):
        return None

    async def execute(self, stmt):
        self.executed.append(stmt)
        result = MagicMock()
        result.scalar_one_or_none.return_value = None
        result.scalar_one.return_value = MagicMock(
            total=1, updated_count=0, skipped_count=0, failed_count=0
        )
        result.scalars.return_value.all.return_value = []
        return result

    def add(self, obj):
        self.added.append(obj)


@pytest.fixture
def fake_session():
    return _FakeSession()


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def _arun(coro):
    """Run an async coroutine synchronously (no pytest-asyncio needed)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# --- Test: skip listing that already has the video ---

def test_process_item_skips_when_video_already_set():
    """_process_item should return 'skipped' when GetItem shows the video is already present."""
    from app.api.listing_video import _process_item

    get_item_mock = AsyncMock(return_value={"video_ids": ["vid123"], "sku": "uke01"})
    revise_mock = AsyncMock()

    async def _run():
        with patch("app.api.listing_video.trading_get_item", get_item_mock), \
             patch("app.api.listing_video.trading_revise_fixed_price_item", revise_mock):
            return await _process_item(
                "job1", "111222333444", "vid123", "tok", asyncio.Semaphore(3), None
            )

    result = _arun(_run())
    assert result == "skipped"
    revise_mock.assert_not_awaited()


# --- Test: update listing that doesn't have the video ---

def test_process_item_revises_when_video_missing():
    from app.api.listing_video import _process_item

    get_item_mock = AsyncMock(return_value={"video_ids": [], "sku": "uke01"})
    revise_mock = AsyncMock()

    async def _run():
        with patch("app.api.listing_video.trading_get_item", get_item_mock), \
             patch("app.api.listing_video.trading_revise_fixed_price_item", revise_mock):
            return await _process_item(
                "job1", "111222333444", "vid123", "tok", asyncio.Semaphore(3), None
            )

    result = _arun(_run())
    assert result == "done"
    revise_mock.assert_awaited_once()


# --- Test: failed revise returns 'failed:<msg>' ---

def test_process_item_returns_failed_on_revise_error():
    from app.api.listing_video import _process_item

    get_item_mock = AsyncMock(return_value={"video_ids": [], "sku": "uke01"})
    revise_mock = AsyncMock(side_effect=RuntimeError("eBay timeout"))

    async def _run():
        with patch("app.api.listing_video.trading_get_item", get_item_mock), \
             patch("app.api.listing_video.trading_revise_fixed_price_item", revise_mock):
            return await _process_item(
                "job1", "111222333444", "vid123", "tok", asyncio.Semaphore(3), None
            )

    result = _arun(_run())
    assert result.startswith("failed:")
    assert "eBay timeout" in result


# --- Test: GetItem failure does not skip (still tries revise) ---

def test_process_item_still_revises_on_get_item_error():
    from app.api.listing_video import _process_item

    get_item_mock = AsyncMock(side_effect=RuntimeError("GetItem failed"))
    revise_mock = AsyncMock()

    async def _run():
        with patch("app.api.listing_video.trading_get_item", get_item_mock), \
             patch("app.api.listing_video.trading_revise_fixed_price_item", revise_mock):
            return await _process_item(
                "job1", "111222333444", "vid123", "tok", asyncio.Semaphore(3), None
            )

    result = _arun(_run())
    # Should not be skipped; revise should be attempted
    assert result == "done"
    revise_mock.assert_awaited_once()


# --- Test: SKUArray optimization in trading_get_seller_list_by_sku ---

def test_sku_array_fast_path_returns_item_ids():
    """When SKUArray returns results the full-scan fallback must not be called."""
    from app.services.ebay_client import trading_get_seller_list_by_sku

    NS = "urn:ebay:apis:eBLBaseComponents"

    def _xml_with_item(item_id: str):
        root_el = Element(f"{{{NS}}}GetSellerListResponse")
        pagination = SubElement(root_el, f"{{{NS}}}PaginationResult")
        pages_el = SubElement(pagination, f"{{{NS}}}TotalNumberOfPages")
        pages_el.text = "1"
        array = SubElement(root_el, f"{{{NS}}}ItemArray")
        item = SubElement(array, f"{{{NS}}}Item")
        iid = SubElement(item, f"{{{NS}}}ItemID")
        iid.text = item_id
        from xml.etree.ElementTree import tostring
        return tostring(root_el, encoding="unicode")

    fake_response = MagicMock()
    fake_response.status_code = 200
    fake_response.text = _xml_with_item("999888777666")
    fake_response.request = MagicMock()

    post_mock = AsyncMock(return_value=fake_response)
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=MagicMock(post=post_mock))
    fake_client.__aexit__ = AsyncMock(return_value=False)

    async def _run():
        results = []
        with patch("app.services.ebay_client.httpx.AsyncClient", return_value=fake_client):
            async for payload in trading_get_seller_list_by_sku("tok", "uke03", "EBAY_GB"):
                results.append(payload)
        return results

    results = _arun(_run())
    # Final element should be the list of item IDs from SKUArray
    assert results[-1] == ["999888777666"]
    # Only one HTTP call (SKUArray page 1) — no full-scan pages
    assert post_mock.await_count == 1


NS = "urn:ebay:apis:eBLBaseComponents"


def _el(tag: str, text: str | None = None, parent=None):
    node = SubElement(parent, f"{{{NS}}}{tag}") if parent is not None else Element(f"{{{NS}}}{tag}")
    if text is not None:
        node.text = text
    return node


def _seller_list_xml(items: list[tuple[str, str | None]], pages: int = 1, ack: str = "Success") -> str:
    root_el = _el("GetSellerListResponse")
    _el("Ack", ack, root_el)
    pagination = _el("PaginationResult", parent=root_el)
    _el("TotalNumberOfPages", str(pages), pagination)
    array = _el("ItemArray", parent=root_el)
    for item_id, sku in items:
        item = _el("Item", parent=array)
        _el("ItemID", item_id, item)
        if sku is not None:
            _el("SKU", sku, item)
    return tostring(root_el, encoding="unicode")


def _revise_xml(ack: str, short_message: str | None = None, severity: str = "Error") -> str:
    root_el = _el("ReviseFixedPriceItemResponse")
    _el("Ack", ack, root_el)
    if short_message is not None:
        errors = _el("Errors", parent=root_el)
        _el("ShortMessage", short_message, errors)
        _el("ErrorCode", "21919188", errors)
        _el("SeverityCode", severity, errors)
    return tostring(root_el, encoding="unicode")


def _mock_response(xml: str, status_code: int = 200):
    fake_response = MagicMock()
    fake_response.status_code = status_code
    fake_response.text = xml
    fake_response.request = MagicMock()
    return fake_response


def _patch_async_client(post_mock):
    fake_client = MagicMock()
    fake_client.__aenter__ = AsyncMock(return_value=MagicMock(post=post_mock))
    fake_client.__aexit__ = AsyncMock(return_value=False)
    return patch("app.services.ebay_client.httpx.AsyncClient", return_value=fake_client)


def test_trading_ack_failure_without_nested_error_element_raises():
    """eBay uses <Errors><ShortMessage>, not <Errors><Error>. Ack=Failure must raise."""
    from app.services.ebay_client import _trading_raise_if_failure

    root = fromstring(_revise_xml("Failure", "This item cannot be revised."))
    with pytest.raises(httpx.HTTPStatusError) as ei:
        _trading_raise_if_failure(root, _mock_response("<unused/>"))
    assert "cannot be revised" in str(ei.value)


def test_trading_ack_warning_does_not_raise():
    from app.services.ebay_client import _trading_raise_if_failure

    root = fromstring(_revise_xml("Warning", "Duration cannot be reduced.", severity="Warning"))
    _trading_raise_if_failure(root, _mock_response("<unused/>"))


def test_trading_ack_success_does_not_raise():
    from app.services.ebay_client import _trading_raise_if_failure

    root = fromstring(_revise_xml("Success"))
    _trading_raise_if_failure(root, _mock_response("<unused/>"))


def test_revise_raises_on_ack_failure():
    from app.services.ebay_client import trading_revise_fixed_price_item

    post_mock = AsyncMock(return_value=_mock_response(_revise_xml("Failure", "This item cannot be revised.")))

    async def _run():
        with _patch_async_client(post_mock):
            await trading_revise_fixed_price_item("tok", "136528644539", "vid123")

    with pytest.raises(httpx.HTTPStatusError) as ei:
        _arun(_run())
    assert "cannot be revised" in str(ei.value)


def test_sku_array_page_ids_treats_wrong_skus_as_ignored():
    from app.services.ebay_client import _gsl_sku_array_page_ids

    root = fromstring(_seller_list_xml([("111111111111", "other-sku"), ("222222222222", "also-wrong")]))
    ids, ignored = _gsl_sku_array_page_ids(root, "uke03")
    assert ignored is True
    assert ids == []


def test_sku_array_page_ids_keeps_matching_and_drops_mismatches():
    from app.services.ebay_client import _gsl_sku_array_page_ids

    root = fromstring(_seller_list_xml([("111111111111", "uke03"), ("222222222222", "other")]))
    ids, ignored = _gsl_sku_array_page_ids(root, "uke03")
    assert ignored is False
    assert ids == ["111111111111"]


def test_sku_array_ignored_falls_back_to_full_scan():
    """If SKUArray returns other SKUs, do not revise those listings; full-scan instead."""
    from app.services.ebay_client import trading_get_seller_list_by_sku

    sku_array_wrong = _mock_response(_seller_list_xml([("111111111111", "other-sku")]))
    full_scan_hit = _mock_response(_seller_list_xml([("999888777666", "uke03")]))
    post_mock = AsyncMock(side_effect=[sku_array_wrong, full_scan_hit])

    async def _run():
        results = []
        with _patch_async_client(post_mock):
            async for payload in trading_get_seller_list_by_sku("tok", "uke03", "EBAY_GB"):
                results.append(payload)
        return results

    results = _arun(_run())
    assert results[-1] == ["999888777666"]
    assert post_mock.await_count == 2
