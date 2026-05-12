"""Regression checks for filtered Sales Analytics profit allocation."""

from decimal import Decimal
from types import SimpleNamespace

from app.api.stock import _allocated_line_net_profits, _analytics_country_codes


def _line(sku: str, quantity: int, line_total: str):
    return SimpleNamespace(sku=sku, quantity=quantity, line_total=Decimal(line_total))


def _sku(landed: str, postage: str = "0"):
    return SimpleNamespace(landed_cost=Decimal(landed), postage_price=Decimal(postage))


def test_analytics_country_codes_merge_us_territories():
    assert _analytics_country_codes("us") == ["US", "PR", "VI"]
    assert _analytics_country_codes("gb") == ["GB"]
    assert _analytics_country_codes("") is None


def test_sku_filtered_profit_uses_full_order_cost_before_allocation(monkeypatch):
    monkeypatch.setattr("app.api.stock.app_settings.PROFIT_TAX_RATE", 0.30, raising=False)
    order = SimpleNamespace(
        total_due_seller=Decimal("100"),
        total_due_seller_currency="GBP",
        price_total=Decimal("100"),
        tax_total=Decimal("0"),
        order_currency="GBP",
        country="US",
        line_items=[
            _line("A", 1, "25"),
            _line("B", 1, "75"),
        ],
    )
    sku_map = {
        "A": _sku("0"),
        "B": _sku("50"),
    }

    allocated = _allocated_line_net_profits(order, sku_map, usd_to_gbp=1.0, sku_filter="A")

    assert allocated == [("A", 1, Decimal("8.750"))]
