"""
Pydantic models and reconciliation checks for GET /api/lender-summary.
Separated so tests do not import SQLAlchemy models.
"""
from decimal import Decimal
from typing import List

from pydantic import BaseModel, Field

# Single source of truth for the amber disclosure box (also bump LENDER_SUMMARY_CACHE_VERSION in api when this changes).
LENDER_SUMMARY_DISCLOSURE = (
    "Gross Profit is Payout minus direct COGS and VAT.\n\n"
    "Ongoing operating expenses are not included (around 3000 GBP per year).\n\n"
    "Figures are management-style operational data derived from order imports. Not a general ledger. "
    "Statutory accounts are the authoritative record."
)


class HeadlineBlock(BaseModel):
    units_sold: int
    gross_revenue_gbp: str
    gross_profit_pre_tax_gbp: str
    gross_margin_percent: str


class WeeklyRow(BaseModel):
    """One row per full Mon–Sun week that lies entirely inside the report from/to (edge weeks omitted)."""

    week_start: str
    week_label: str
    units: int
    revenue_gbp: str
    gross_profit_gbp: str
    margin_percent: str


class RollingPeriodRow(BaseModel):
    """Fixed rolling window ending on the report `to` date (inclusive; e.g. 30 = last 30 calendar days)."""

    label: str
    window_days: int
    period_start: str
    period_end: str
    units: int
    revenue_gbp: str
    gross_profit_gbp: str
    margin_percent: str


class GeographyRow(BaseModel):
    label: str
    code: str
    units: int
    revenue_gbp: str
    gross_profit_gbp: str
    pct_of_total_revenue: str


class MethodologyBlock(BaseModel):
    usd_to_gbp_rate: float
    eur_to_gbp_rate: float
    uk_vat_default_rate: float
    generated_at_utc: str
    company_footer_note: str = ""


class LenderSummaryResponse(BaseModel):
    period_from: str
    period_to: str
    generated_at_utc: str
    disclosure: str = Field(default=LENDER_SUMMARY_DISCLOSURE)
    headline: HeadlineBlock
    weekly: List[WeeklyRow]
    rolling_periods: List[RollingPeriodRow]
    geography: List[GeographyRow]
    methodology: MethodologyBlock


def lender_reconciliation_errors(p: LenderSummaryResponse) -> List[str]:
    """
    Check geography sub-totals to headline. Weekly is full weeks only and does not partition the full period.
    """
    errs: List[str] = []
    op = Decimal(p.headline.gross_profit_pre_tax_gbp)
    rev = Decimal(p.headline.gross_revenue_gbp)
    sg = sum(Decimal(r.gross_profit_gbp) for r in p.geography)
    if op != sg:
        errs.append(f"geography gross profit sum {sg} != headline {op}")
    sgr = sum(Decimal(r.revenue_gbp) for r in p.geography)
    if rev != sgr:
        errs.append(f"geography revenue sum {sgr} != headline {rev}")
    return errs
