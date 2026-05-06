"""Behaviour checks for monthly-profit calendar helpers (mirrors stock.py semantics)."""

from datetime import date


def _month_is_partial(month_start: date, today: date) -> bool:
    return (month_start.year, month_start.month) >= (today.year, today.month)


def test_month_is_partial_current_and_future():
    today = date(2026, 5, 15)
    assert _month_is_partial(date(2026, 5, 1), today)
    assert _month_is_partial(date(2026, 12, 1), today)
    assert not _month_is_partial(date(2026, 4, 1), today)
    assert not _month_is_partial(date(2025, 12, 1), today)
