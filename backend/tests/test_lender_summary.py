"""Reconciliation rules for GET /api/lender-summary (pre-tax gross profit)."""

from app.schemas.lender_summary import (
    HeadlineBlock,
    GeographyRow,
    LenderSummaryResponse,
    MethodologyBlock,
    RollingPeriodRow,
    WeeklyRow,
    lender_reconciliation_errors,
)


def _m() -> MethodologyBlock:
    return MethodologyBlock(
        usd_to_gbp_rate=0.79,
        eur_to_gbp_rate=0.86,
        uk_vat_default_rate=0.2,
        generated_at_utc="2024-01-01T00:00:00Z",
    )


_RP = [
    RollingPeriodRow(
        label="Last 30 days",
        window_days=30,
        period_start="2024-01-01",
        period_end="2024-01-31",
        units=0,
        revenue_gbp="0.00",
        gross_profit_gbp="0.00",
        margin_percent="0.00",
    ),
    RollingPeriodRow(
        label="Last 90 days",
        window_days=90,
        period_start="2023-11-03",
        period_end="2024-01-31",
        units=0,
        revenue_gbp="0.00",
        gross_profit_gbp="0.00",
        margin_percent="0.00",
    ),
    RollingPeriodRow(
        label="Last 180 days",
        window_days=180,
        period_start="2023-08-04",
        period_end="2024-01-31",
        units=0,
        revenue_gbp="0.00",
        gross_profit_gbp="0.00",
        margin_percent="0.00",
    ),
]


def test_lender_reconciliation_ok_aligned_totals():
    op = "100.00"
    rev = "500.00"
    p = LenderSummaryResponse(
        period_from="2024-01-01",
        period_to="2024-01-31",
        generated_at_utc="2024-01-01T00:00:00Z",
        headline=HeadlineBlock(
            units_sold=10,
            gross_revenue_gbp=rev,
            gross_profit_pre_tax_gbp=op,
            gross_margin_percent="20.00",
        ),
        weekly=[
            WeeklyRow(
                week_start="2024-01-01",
                week_label="1–7 January 2024",
                units=10,
                revenue_gbp="200.00",
                gross_profit_gbp="40.00",
                margin_percent="20.00",
            )
        ],
        rolling_periods=_RP,
        geography=[
            GeographyRow(
                label="United Kingdom",
                code="UK",
                units=10,
                revenue_gbp=rev,
                gross_profit_gbp=op,
                pct_of_total_revenue="100.00",
            ),
            GeographyRow(
                label="Germany",
                code="DE",
                units=0,
                revenue_gbp="0.00",
                gross_profit_gbp="0.00",
                pct_of_total_revenue="0.00",
            ),
            GeographyRow(
                label="United States",
                code="US",
                units=0,
                revenue_gbp="0.00",
                gross_profit_gbp="0.00",
                pct_of_total_revenue="0.00",
            ),
            GeographyRow(
                label="Other",
                code="OTHER",
                units=0,
                revenue_gbp="0.00",
                gross_profit_gbp="0.00",
                pct_of_total_revenue="0.00",
            ),
        ],
        methodology=_m(),
    )
    assert lender_reconciliation_errors(p) == []


def test_lender_reconciliation_fails_mismatched_geography():
    p = LenderSummaryResponse(
        period_from="2024-01-01",
        period_to="2024-01-31",
        generated_at_utc="2024-01-01T00:00:00Z",
        headline=HeadlineBlock(
            units_sold=10,
            gross_revenue_gbp="500.00",
            gross_profit_pre_tax_gbp="100.00",
            gross_margin_percent="20.00",
        ),
        weekly=[],
        rolling_periods=_RP,
        geography=[
            GeographyRow(
                label="United Kingdom",
                code="UK",
                units=10,
                revenue_gbp="500.00",
                gross_profit_gbp="50.00",
                pct_of_total_revenue="100.00",
            ),
            GeographyRow(
                label="Germany", code="DE", units=0,
                revenue_gbp="0.00", gross_profit_gbp="0.00", pct_of_total_revenue="0.00",
            ),
            GeographyRow(
                label="United States", code="US", units=0,
                revenue_gbp="0.00", gross_profit_gbp="0.00", pct_of_total_revenue="0.00",
            ),
            GeographyRow(
                label="Other", code="OTHER", units=0,
                revenue_gbp="0.00", gross_profit_gbp="0.00", pct_of_total_revenue="0.00",
            ),
        ],
        methodology=_m(),
    )
    err = lender_reconciliation_errors(p)
    assert any("geography gross profit" in e for e in err)
