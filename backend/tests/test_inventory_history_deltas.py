"""Delta logic for inventory history."""
from datetime import datetime, timezone

from app.services.inventory_history import HistoryPoint, attach_deltas


def test_attach_deltas_two_observations():
    t0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 1, 2, 12, 0, 0, tzinfo=timezone.utc)
    pts = [
        HistoryPoint(t0, "OC1", "UK", 10, 2, 0),
        HistoryPoint(t1, "OC1", "UK", 8, 2, 0),
    ]
    rows = attach_deltas(pts)
    assert len(rows) == 2
    assert rows[0]["delta_available"] is None
    assert rows[1]["delta_available"] == -2
    assert rows[1]["delta_in_transit"] == 0


def test_attach_deltas_separate_regions():
    t = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    pts = [
        HistoryPoint(t, "OC1", "UK", 5, 0, 0),
        HistoryPoint(t, "OC1", "US-South", 3, 1, 0),
    ]
    rows = attach_deltas(pts)
    assert len(rows) == 2
    assert all(r["delta_available"] is None for r in rows)
