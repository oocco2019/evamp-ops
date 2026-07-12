"""Tests for analytics date preset helpers."""

from datetime import date

from app.utils.date_ranges import complete_days_range, latest_complete_day


def test_latest_complete_day_is_yesterday(monkeypatch):
    monkeypatch.setattr("app.utils.date_ranges.date", type("D", (), {"today": staticmethod(lambda: date(2026, 7, 12))}))
    assert latest_complete_day() == date(2026, 7, 11)


def test_complete_days_range_excludes_today(monkeypatch):
    monkeypatch.setattr("app.utils.date_ranges.date", type("D", (), {"today": staticmethod(lambda: date(2026, 7, 12))}))
    start, end = complete_days_range(7)
    assert start == date(2026, 7, 5)
    assert end == date(2026, 7, 11)
