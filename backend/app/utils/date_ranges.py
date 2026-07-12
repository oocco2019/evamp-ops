"""Shared inclusive date windows for analytics presets (match frontend datePeriodPresets)."""

from datetime import date, timedelta


def latest_complete_day() -> date:
    """Yesterday — last fully completed calendar day."""
    return date.today() - timedelta(days=1)


def complete_days_range(n: int) -> tuple[date, date]:
    """n complete calendar days ending yesterday (e.g. 7d on 12 Jul → 5 Jul–11 Jul)."""
    end = latest_complete_day()
    start = date.today() - timedelta(days=n)
    return start, end
