# Sales Analytics page – behavior and decisions

This doc captures how the Sales Analytics page works and why, so context is preserved.
UI copy on the page is kept minimal; behaviour that used to live in on-page blurbs is documented here.

## What’s on the page

- **Filters:** Period presets / From–To, Group by (day/week/month), Source (All / eBay / Shopify), Country, SKU. A **Refunds only** toggle sits next to the Filters heading. Changing any filter refetches analytics automatically (no Apply button).
- **Default date range:** last **90 complete calendar days** ending yesterday (not including today). See `defaultAnalyticsRange()` / `completeDaysRange(90)` in `frontend/src/utils/datePeriodPresets.ts`.
- **Cards:** Units sold (period total + Today side stat); Profit (GBP and EUR after 30% tax, + Today side stat) – profit rules in [ANALYTICS_PROFIT_LOGIC.md](ANALYTICS_PROFIT_LOGIC.md).
- **Order details (separate page):** For **line-level transparency** (payout, COGS, VAT, allocated profit per line), open the link at the **bottom of the Sales Analytics page** (`/order-details`). It is not in the top nav. See [ORDER_DETAILS_AND_ANALYTICS_TRANSPARENCY.md](ORDER_DETAILS_AND_ANALYTICS_TRANSPARENCY.md).
- **Chart:** Units sold by period (bar chart).
- **Tables:** Sales by Country; Sales by SKU. Both show quantity sold and profit (GBP only in the tables).

## Decisions and behavior

### Profit (not “qty × SKU profit_per_unit”)

- An old UI line under Sales by SKU said *“Profit = quantity sold × profit per unit (set in SKU Manager)”*. That was **incorrect / outdated** and was **removed** from the UI.
- Table and card **profit** use the order-level model in [ANALYTICS_PROFIT_LOGIC.md](ANALYTICS_PROFIT_LOGIC.md): Total Due Seller − landed − postage (− Shopify surcharge/fees as applicable) − UK VAT, then × (1 − `PROFIT_TAX_RATE`). Allocated to SKUs/countries by line share.
- SKU Manager’s optional `profit_per_unit` field is **not** what Sales Analytics multiplies for these totals.

### Profit in GBP and EUR

- **Dual currency (GBP / EUR)** is shown **only on the Profit card** at the top.
- The Sales by SKU and Sales by Country tables show profit in **GBP only** (£).
- EUR on the card is derived from the same GBP total using `GBP_TO_EUR_RATE` (1.16) so it stays consistent.

### Table sort persistence

- Sort column and direction for **Sales by SKU** and **Sales by Country** are stored in `localStorage`:
  - `salesAnalytics.skuSort` – e.g. `{ "key": "profit", "dir": "desc" }`
  - `salesAnalytics.countrySort` – same shape.
- On load, saved sort is restored; on each header click, the new sort is persisted. Survives refresh and navigation.

### Background incremental import on open

- **Every time you open Sales Analytics**, the app starts an **incremental import** in the background (`POST /api/stock/import` with `mode: 'incremental'`, includes Shopify when configured).
- The page renders and shows analytics immediately; it does not wait for the import.
- When the import **finishes successfully**, the analytics query is invalidated so data refetches and figures update.
- If the import fails, the failure is ignored in the background; current data stays visible.

### Latest orders table removed

- The “Latest orders” table (and its Backfill Order earnings button and “Show 25/50/100 orders” selector) was removed from Sales Analytics. The backfill endpoint (`POST /api/stock/orders/backfill-order-earnings`) still exists on the backend if needed elsewhere.

### Order data retention

- Sales Analytics reads **only from your database** (tables `orders`, `line_items`, `skus`). It does not call eBay/Shopify when loading charts (import is separate).
- Order data is imported via the stock/order import (e.g. incremental import when you open Sales Analytics). Once imported, it persists in your DB. So you can still run analytics on that data even after marketplaces no longer return those orders (e.g. after their retention window).
