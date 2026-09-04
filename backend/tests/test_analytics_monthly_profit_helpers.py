"""Behaviour checks for monthly-profit calendar helpers (mirrors stock.py semantics)."""

from decimal import Decimal
from datetime import date

from app.api.stock import _profit_for_display
from app.core.config import settings as app_settings


def _month_is_partial(month_start: date, today: date) -> bool:
    return (month_start.year, month_start.month) >= (today.year, today.month)


def test_month_is_partial_current_and_future():
    today = date(2026, 5, 15)
    assert _month_is_partial(date(2026, 5, 1), today)
    assert _month_is_partial(date(2026, 12, 1), today)
    assert not _month_is_partial(date(2026, 4, 1), today)
    assert not _month_is_partial(date(2025, 12, 1), today)


def test_profit_for_display_tax_toggle():
    gross = Decimal("100")
    rate = Decimal(str(getattr(app_settings, "PROFIT_TAX_RATE", 0.32)))
    expected_after_tax = gross * (Decimal("1") - rate)

    assert _profit_for_display(gross, profit_tax_included=True) == expected_after_tax
    assert _profit_for_display(gross, profit_tax_included=False) == gross


def test_add_months_spans_year():
    from app.api.stock import _add_months

    assert _add_months(date(2025, 11, 1), 2) == date(2026, 1, 1)
    assert _add_months(date(2026, 1, 1), -1) == date(2025, 12, 1)
