"""Tests for _order_profit_gbp refund (inventory returned) vs normal COGS."""

from decimal import Decimal

from app.api.stock import _order_profit_gbp, _uk_vat_gbp


def test_normal_order_full_cogs():
    """Non-UK: no UK VAT line."""
    gross = _order_profit_gbp(
        total_due_seller=Decimal("100"),
        price_total=Decimal("120"),
        tax_total=Decimal("0"),
        order_currency="GBP",
        country="US",
        line_cost_usd_total=Decimal("50"),
        line_postage_usd_total=Decimal("5"),
        usd_to_gbp=0.79,
    )
    assert gross is not None
    # 100 - 50*0.79 - 0 = 60.5
    assert gross == Decimal("60.5")


def test_uk_no_ebay_tax_uses_default_vat():
    """GB + zero tax_total: VAT extracted from VAT-inclusive total (20% rate → ×20/120)."""
    gross = _order_profit_gbp(
        total_due_seller=Decimal("100"),
        price_total=Decimal("120"),
        tax_total=Decimal("0"),
        order_currency="GBP",
        country="GB",
        line_cost_usd_total=Decimal("50"),
        line_postage_usd_total=Decimal("5"),
        usd_to_gbp=0.79,
    )
    assert gross is not None
    # vat = 120 * 0.2/1.2 = 20; 100 - 39.5 - 20 = 40.5
    assert gross == Decimal("40.5")


def test_uk_default_vat_is_vat_inclusive_extract():
    """£129.99 gross @ 20% VAT → £21.67 tax in price, not £26 (20% of gross)."""
    assert _uk_vat_gbp("GB", Decimal("0"), Decimal("129.99"), Decimal("1")) == Decimal("21.67")


def test_uk_positive_tax_total_uses_ebay_only():
    gross = _order_profit_gbp(
        total_due_seller=Decimal("100"),
        price_total=Decimal("120"),
        tax_total=Decimal("20"),
        order_currency="GBP",
        country="GB",
        line_cost_usd_total=Decimal("50"),
        line_postage_usd_total=Decimal("5"),
        usd_to_gbp=0.79,
    )
    assert gross is not None
    # vat from eBay = 20, not 24; 100 - 39.5 - 20 = 40.5
    assert gross == Decimal("40.5")


def test_refund_negative_payout_only_double_postage_not_landed():
    """total_due_seller <= 0: cost = 2 * postage_usd * usd_to_gbp, not full landed+postage."""
    line_cost_usd = Decimal("80")
    line_postage_usd = Decimal("8")
    usd_to_gbp = 0.79
    gross = _order_profit_gbp(
        total_due_seller=Decimal("-0.48"),
        price_total=Decimal("129.99"),
        tax_total=Decimal("0"),
        order_currency="GBP",
        country="GB",
        line_cost_usd_total=line_cost_usd,
        line_postage_usd_total=line_postage_usd,
        usd_to_gbp=usd_to_gbp,
    )
    assert gross is not None
    postage_gbp = line_postage_usd * Decimal(str(usd_to_gbp))
    cost_gbp = Decimal("2") * postage_gbp
    expected = Decimal("-0.48") - cost_gbp
    assert gross == expected


def test_refund_zero_payout_uses_postage_cost():
    gross = _order_profit_gbp(
        total_due_seller=Decimal("0"),
        price_total=Decimal("100"),
        tax_total=Decimal("0"),
        order_currency="GBP",
        country="GB",
        line_cost_usd_total=Decimal("50"),
        line_postage_usd_total=Decimal("10"),
        usd_to_gbp=1.0,
    )
    assert gross is not None
    # cost = 2*10*1 = 20; UK VAT = 0 on refund clawback
    assert gross == Decimal("0") - Decimal("20")
