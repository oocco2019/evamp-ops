# Sales Analytics page – behavior and decisions

This doc captures how the Sales Analytics page works and why, so context is preserved.

## What’s on the page

- **Filters:** From / To date, Group by (day/week/month), Country, SKU. All drive the analytics queries.
- **Cards:** Units sold (total); Profit (GBP and EUR, after 30% tax) – see [ANALYTICS_PROFIT_LOGIC.md](ANALYTICS_PROFIT_LOGIC.md).
- **Chart:** Units sold by period (bar chart).
- **Tables:** Sales by Country; Sales by SKU. Both show quantity sold and profit (GBP only in the tables).

## Decisions and behavior

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

- **Every time you open Sales Analytics**, the app starts an **incremental import** in the background (`POST /api/stock/import` with `mode: 'incremental'`).
- The page renders and shows analytics immediately; it does not wait for the import.
- When the import **finishes successfully**, the analytics query is invalidated so data refetches and figures update.
- If the import fails, the failure is ignored in the background; current data stays visible.

### Latest orders table removed

- The “Latest orders” table (and its Backfill Order earnings button and “Show 25/50/100 orders” selector) was removed from Sales Analytics. The backfill endpoint (`POST /api/stock/orders/backfill-order-earnings`) still exists on the backend if needed elsewhere.

### Order data retention

- Sales Analytics reads **only from your database** (tables `orders`, `line_items`, `skus`). It does not call eBay when loading the page.
- Order data is imported from eBay via the stock/order import (e.g. incremental import when you open Sales Analytics). Once imported, it persists in your DB. So you can still run analytics on that data even after eBay no longer returns those orders (e.g. after their retention window).
