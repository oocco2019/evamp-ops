# Sales Analytics: profit calculation logic

This document describes how profit is computed so the context is not lost when changing code or config.

**Related:** [ORDER_DETAILS_AND_ANALYTICS_TRANSPARENCY.md](ORDER_DETAILS_AND_ANALYTICS_TRANSPARENCY.md) explains the **Order details** dashboard (why it exists, column meanings, and how it helped validate these rules).

## Gross profit per order (GBP)

1. **Total Due Seller (Order Earnings)** – from eBay, in GBP. Treated as the order’s gross payout.
2. **Cost (landed + postage)** – from SKU Manager, in USD. Per line: `(landed_cost + postage_price) * quantity`. Sum over lines, then convert to GBP using `USD_TO_GBP_RATE`.
3. **UK only (ship-to GB): VAT** – subtract VAT in GBP.  
   - If eBay’s `tax_total` is **greater than zero**, use that amount (order currency × FX to GBP, same rate as `price_total`).  
   - If `tax_total` is **missing or zero**, treat **`price_gbp`** as **VAT-inclusive** at **`UK_VAT_DEFAULT_RATE`** (default **20%**): VAT = **`price_gbp × rate / (1 + rate)`** (same as **gross ÷ 6** at 20%). Not “20% of gross” (which would overstate VAT).

### UK: your real-world flow vs what this dashboard models

**How you described it (UK seller):** After eBay pays you, you pay postage and stock, and **you pay VAT on the sales price** as part of your own VAT obligations. eBay does not always populate `tax_total` on every UK order.

**What the app does:** For GB orders it subtracts eBay `tax_total` when present; otherwise it extracts the VAT **inside** the VAT-inclusive price using **`UK_VAT_DEFAULT_RATE`** (default 20%).

**Formula (non-UK):**

`gross_profit = Total Due Seller (GBP) - (landed+postage in USD → GBP)`

**Formula (UK):**

`gross_profit = Total Due Seller (GBP) - (landed+postage in USD → GBP) - VAT (GBP)`

where **VAT (GBP)** = eBay `tax_total` → GBP if `tax_total > 0`, else **`price_gbp × UK_VAT_DEFAULT_RATE / (1 + UK_VAT_DEFAULT_RATE)`** (VAT-inclusive extract; default rate 20%).

Order currency (EUR, USD, etc.) is converted to GBP using `EUR_TO_GBP_RATE` or `USD_TO_GBP_RATE` in config.

## Refunds with inventory returned (total due seller ≤ 0)

When **Total Due Seller** is **zero or negative** (net clawback after a refund), the model assumes **stock is returned** and you can resell it: **landed cost is not treated as lost**.

**Cost in that case** is only **2× outbound postage** (outbound + return), in USD summed per line as `postage_price × quantity`, then multiplied by 2, then converted to GBP with `USD_TO_GBP_RATE` — not landed + postage.

**Detection:** `total_due_seller <= 0` (same currency as stored for the order; typically GBP for UK sellers).

**UK VAT** is treated as **£0** on these orders (refund reverses the sale for VAT in this model), alongside 2× postage-only cost.

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
| `UK_VAT_DEFAULT_RATE` | GB orders only: when eBay `tax_total` is 0/null, VAT = order total (GBP) × `rate/(1+rate)` (VAT-inclusive). Default 0.20 | 0.20    |
| `GBP_TO_EUR_RATE` | Multiply GBP profit by this to get EUR for display. E.g. 1.16 = 1 GBP = 1.16 EUR | 1.16    |

## When profit updates

- **Order/earnings data** – from eBay import and backfill. Opening Sales Analytics triggers a background incremental import; when it completes, analytics refetches so figures stay up to date. Backfill is still available via the API if needed.
- **SKU costs** – from SKU Manager (landed cost, postage in USD). Editing a SKU and saving invalidates the analytics query so Sales Analytics refetches when you view it (or when the page is already open and refetches on invalidation).
