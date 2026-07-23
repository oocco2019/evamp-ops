"""Unit tests for burn-rate trend helpers."""
from datetime import date

from app.services.stock_burn_trend import (
    band_ratio,
    cover_diverges,
    evaluate_trend_verdict,
    is_dead_burn_trend_row,
    is_low_sample,
    reorder_suppressed,
    window_start,
)
from app.services.stock_forecast import _reorder_plan, effective_reorder_lead_days


def test_window_start_inclusive():
    to = date(2026, 7, 22)
    assert window_start(to, 30) == date(2026, 6, 23)
    assert window_start(to, 1) == to


def test_band_ratio_thresholds():
    assert band_ratio(1.26) == "accelerating"
    assert band_ratio(1.25) == "stable"
    assert band_ratio(0.80) == "stable"
    assert band_ratio(0.79) == "decaying"


def test_evaluate_trend_30_gate_bands():
    ratio, source, verdict, low = evaluate_trend_verdict(
        burn_30=2.0,
        burn_90=1.5,
        burn_180=1.0,
        units_30=20,
        units_90=50,
        in_stock_days_30=25,
        in_stock_days_90=80,
    )
    assert source == 30
    assert ratio == 2.0
    assert verdict == "accelerating"
    assert low is False


def test_evaluate_trend_30_low_sample():
    _, _, verdict, low = evaluate_trend_verdict(
        burn_30=1.0,
        burn_90=1.0,
        burn_180=1.0,
        units_30=20,
        units_90=50,
        in_stock_days_30=10,  # < 0.6 * 30
        in_stock_days_90=80,
    )
    assert verdict == "stable"
    assert low is True


def test_evaluate_trend_fallback_insufficient_volume():
    ratio, source, verdict, low = evaluate_trend_verdict(
        burn_30=3.0,
        burn_90=1.5,
        burn_180=1.0,
        units_30=5,
        units_90=20,
        in_stock_days_30=20,
        in_stock_days_90=50,  # < 0.6 * 90 → low sample on 90
    )
    assert source == 90
    assert ratio == 1.5
    assert verdict == "insufficient_volume"
    assert low is True


def test_evaluate_trend_neither_gate():
    ratio, source, verdict, low = evaluate_trend_verdict(
        burn_30=2.0,
        burn_90=1.5,
        burn_180=1.0,
        units_30=5,
        units_90=10,
        in_stock_days_30=20,
        in_stock_days_90=80,
    )
    assert ratio is None and source is None and verdict is None and low is False


def test_evaluate_trend_no_burn180():
    ratio, source, verdict, _ = evaluate_trend_verdict(
        burn_30=2.0,
        burn_90=1.5,
        burn_180=None,
        units_30=20,
        units_90=50,
        in_stock_days_30=25,
        in_stock_days_90=80,
    )
    assert ratio is None and source is None and verdict is None


def test_cover_diverges():
    assert cover_diverges(100.0, 50.0) is True  # 50% relative to max
    assert cover_diverges(100.0, 80.0) is False  # 20%
    assert cover_diverges(None, 50.0) is False


def test_is_low_sample():
    assert is_low_sample(17, 30) is True
    assert is_low_sample(18, 30) is False


def test_dead_row_predicate():
    assert is_dead_burn_trend_row(0, 0, None, None, None) is True
    assert is_dead_burn_trend_row(0, 0, 0.0, None, None) is True
    assert is_dead_burn_trend_row(0, 0, 0.5, None, None) is False
    assert is_dead_burn_trend_row(1, 0, None, None, None) is False
    assert is_dead_burn_trend_row(0, 5, None, None, None) is False


def test_reorder_suppressed_decaying_long_cover():
    assert reorder_suppressed("decaying", 181.0) is True
    assert reorder_suppressed("decaying", 180.0) is False
    assert reorder_suppressed("accelerating", 200.0) is False
    assert reorder_suppressed(None, 200.0) is False


def test_reorder_plan_respects_explicit_lead():
    qty, reorder_by, days_until = _reorder_plan("2026-12-01", 2.0, date(2026, 6, 1), lead_days=90)
    assert qty == 180
    assert reorder_by == "2026-09-02"
    assert days_until == 93.0

    qty2, _, _ = _reorder_plan("2026-12-01", 2.0, date(2026, 6, 1), lead_days=100)
    assert qty2 == 200


def test_effective_reorder_lead_days_non_negative():
    assert effective_reorder_lead_days() >= 0
