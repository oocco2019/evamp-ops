# Sales Analytics: profit calculation logic

This document describes how profit is computed so the context is not lost when changing code or config.

## Gross profit per order (GBP)

1. **Total Due Seller (Order Earnings)** – from eBay, in GBP. Treated as the order’s gross payout.
2. **Cost (landed + postage)** – from SKU Manager, in USD. Per line: `(landed_cost + postage_price) * quantity`. Sum over lines, then convert to GBP using `USD_TO_GBP_RATE`.
3. **2% of Price Total** – order’s `price_total` (in order currency) converted to GBP, then 2% subtracted.
4. **UK only: VAT** – if order country is GB, subtract the order’s `tax_total` (converted to GBP).

**Formula (non-UK):**

`gross_profit = Total Due Seller (GBP) - (landed+postage in USD → GBP) - 2% of Price Total (GBP)`

**Formula (UK):**

`gross_profit = Total Due Seller (GBP) - (landed+postage in USD → GBP) - VAT (tax_total in GBP) - 2% of Price Total (GBP)`

Order currency (EUR, USD, etc.) is converted to GBP using `EUR_TO_GBP_RATE` or `USD_TO_GBP_RATE` in config.

## Profit after tax (what is displayed)

When you “take out” profit you pay tax on it (e.g. 30%). The app shows **profit after that tax** (take-home).

**Formula:**

`displayed_profit = gross_profit * (1 - PROFIT_TAX_RATE)`

- Default `PROFIT_TAX_RATE = 0.30` (30% tax → 70% take-home).
- Set in `.env` as `PROFIT_TAX_RATE=0.30` (or override in config).

All profit values in Sales Analytics (by SKU, by country, total Profit card) use this after-tax value.

## Config (.env)

| Variable           | Meaning                          | Example |
|--------------------|----------------------------------|---------|
| `USD_TO_GBP_RATE` | Multiply USD amounts by this to get GBP | 0.79    |
| `EUR_TO_GBP_RATE` | Multiply EUR amounts by this to get GBP | 0.86    |
| `PROFIT_TAX_RATE` | Tax rate on profit (0–1). Displayed profit = gross × (1 - rate) | 0.30    |
| `GBP_TO_EUR_RATE` | Multiply GBP profit by this to get EUR for display. E.g. 1.16 = 1 GBP = 1.16 EUR | 1.16    |

## When profit updates

- **Order/earnings data** – from eBay import and backfill. Opening Sales Analytics triggers a background incremental import; when it completes, analytics refetches so figures stay up to date. Backfill is still available via the API if needed.
- **SKU costs** – from SKU Manager (landed cost, postage in USD). Editing a SKU and saving invalidates the analytics query so Sales Analytics refetches when you view it (or when the page is already open and refetches on invalidation).
