# Order Details dashboard and analytics transparency

This document explains **why** the Order Details feature exists, **what** it exposes, and **how** it ties to the profit engine so you can **audit numbers, spot inconsistencies, and fix formulas** before they distort business decisions.

## Why this exists

Aggregated views (Sales Analytics by SKU, by country, summary cards) answer “how much did we make?” but they **hide the intermediate steps**: payout per order, COGS, VAT assumptions, and how each line item’s share of profit is allocated.

**Goal:** build a **line-level dashboard** that:

1. **Transparency** – Every order line shows the same inputs and outputs the backend uses for profit, in one place.
2. **Visibility** – You can filter by date range, country, and SKU to isolate segments (e.g. one SKU, one marketplace) without guessing.
3. **Error detection** – When a formula or assumption is wrong (wrong VAT basis, double-counting fee, refund treated like a full COGS loss, currency shown as £ when the amount is USD), you can **see the mismatch** on real rows and correct the logic in code or config.

**Related:** High-level profit rules are documented in [ANALYTICS_PROFIT_LOGIC.md](ANALYTICS_PROFIT_LOGIC.md). Sales Analytics page behaviour is in [SALES_ANALYTICS.md](SALES_ANALYTICS.md).

## What was built

### Frontend

- **Route:** `/order-details` (nav: **Order details**).
- **Page:** `frontend/src/pages/OrderDetails.tsx`
  - Filters: period presets, from/to dates, country, SKU (options from `GET /api/stock/analytics/filter-options`).
  - Summary cards: row count, units, payout sum (orders counted once), sum of line costs, sum of line gross/net profit.
  - **Wide table:** one row per **line item** (or filtered SKU lines), with order-level columns repeated per line so you can reconcile to eBay and SKU Manager.

### Backend

- **Endpoint:** `GET /api/stock/analytics/order-details`
  - Query params: `from`, `to` (dates), optional `country`, optional `sku` (case-insensitive line filter).
  - Response: `rows` (line-level detail) + `totals` (aggregates for the filtered set).
- **Implementation:** `backend/app/api/stock.py` – `OrderDetailRow`, `OrderDetailsTotals`, `get_analytics_order_details`.

Profit **per order** uses the same core function as **`/analytics/by-sku`** and **`/analytics/by-country`**: `_order_profit_gbp`, then **allocated to lines** by `line_total / order price_total` (same as by-SKU when a SKU filter applies).

## Column reference (mental model)

| Area | Meaning |
|------|--------|
| **Order / marketplace** | `order_date`, `ebay_order_id`, `country`, `sku`, `quantity`. |
| **Payout** | **Due seller** – `total_due_seller` in **`total_due_seller_currency`** (often GBP for UK sellers). |
| **Buyer / eBay list price** | **Buyer total**, **Tax**, **Line total** – amounts in **`order_currency`** (USD, EUR, GBP, …); **Cur** shows that code. |
| **GBP bridge** | **Order GBP** – order total converted to GBP for internal consistency with COGS. |
| **COGS (SKU Manager)** | **Landed GBP**, **Post GBP**, **Line cost**, **Order cost** – USD costs × `USD_TO_GBP_RATE`, with **refund mode** adjusting line display (see below). |
| **UK VAT (analytics)** | **VAT** – not eBay’s `tax_total` column when that is empty; see [ANALYTICS_PROFIT_LOGIC.md](ANALYTICS_PROFIT_LOGIC.md). |
| **Profit** | **Ord gross / Ord net** – order-level profit after `_order_profit_gbp` and `_profit_after_tax`; **Line gross / Line net** – same order numbers **× allocation share**. |
| **Tax %** | **PROFIT_TAX_RATE** (e.g. 30%) on **profit** – **not** UK VAT rate. |

## Issues this dashboard helped surface (and how logic evolved)

These are **examples** of why transparency matters; the code is the source of truth.

1. **Refunds** – Net payout (`total_due_seller`) can be **negative or zero** while the original order total still appears in history. Treating full **landed + postage** as lost implied **COGS** when stock is returned. **Rule:** if `total_due_seller <= 0`, **cost** = **2× postage** (outbound + return) in USD→GBP; **UK VAT** for that scenario = **£0** (refund reverses the sale in this model). See [ANALYTICS_PROFIT_LOGIC.md](ANALYTICS_PROFIT_LOGIC.md) § Refunds.

2. **UK VAT when eBay shows no tax** – Empty or zero `tax_total` led to **£0** VAT in analytics while real liability still exists. **Rule:** default **VAT extracted from VAT-inclusive gross** at `UK_VAT_DEFAULT_RATE` (default 20%): `price_gbp × rate / (1 + rate)` (equivalent to **gross ÷ 6** at 20%). **Not** `0.20 × gross` (which overstated VAT, e.g. £26 vs ~£21.67 on £129.99).

3. **Currency display** – Showing **£** for US/EU **tax** and buyer totals when amounts were in **USD/EUR**. **Fix:** format **Due seller**, **Buyer total**, **Tax**, **Line total** with `Intl` using the correct ISO currency (`order_currency` / `total_due_seller_currency`).

4. **“2% of price”** – A flat **2% of order total** was deducted as a generic fee. **Removed** from `_order_profit_gbp` so profit reflects **payout − COGS − UK VAT** (and refund rules) without that extra line.

5. **React Query / formatting** – Edge cases (e.g. `Intl`, loading flags) could blank the page. **Fix:** defensive `fmtMoney`, `isPending` + `isLoading` fallback, Axios error `detail` surfacing.

## Configuration (environment)

| Variable | Role |
|----------|------|
| `USD_TO_GBP_RATE` | SKU costs (USD) and order FX when currency is not GBP/EUR. |
| `EUR_TO_GBP_RATE` | Order amounts in EUR → GBP. |
| `PROFIT_TAX_RATE` | Tax on **profit** (e.g. 0.30 = 30%) – **Ord net** / **Line net**. |
| `UK_VAT_DEFAULT_RATE` | GB orders only: when eBay `tax_total` is 0/null, VAT = inclusive extract **× rate/(1+rate)**. |
| `GBP_TO_EUR_RATE` | EUR display on Sales Analytics cards. |

Full table: [ANALYTICS_PROFIT_LOGIC.md](ANALYTICS_PROFIT_LOGIC.md) § Config.

## How to verify

1. Pick a **known order** in eBay (payout, buyer total, currency).
2. Open **Order details**, set the date range and filters, find the row.
3. Check **Due seller** vs eBay **Order earnings**; **Buyer total** / **Tax** in **Cur** vs eBay order summary.
4. Recompute **Ord gross** mentally: payout − order cost (and VAT per refund rules) should match `_order_profit_gbp` (see code).
5. After changing **SKU costs** or **env**, refresh and confirm **Line cost** / **Order cost** move as expected.

## Tests

- **`backend/tests/test_order_profit_refund.py`** – `_order_profit_gbp` scenarios: non-UK, UK VAT inclusive default, eBay tax, refunds (no VAT, postage-only cost).

Run: `pytest backend/tests/test_order_profit_refund.py -v`

## API client (frontend)

- Types: `OrderDetailRow`, `OrderDetailsResponse` in `frontend/src/services/api.ts`.
- Method: `stockAPI.getOrderDetails({ from, to, country?, sku? })`.

## Changelog (conceptual)

- Order details endpoint + UI.
- Refund cost + zero VAT on refund clawback.
- UK VAT default: VAT-inclusive extraction; removed 2% fee from profit.
- Currency-aware display for marketplace amounts.
- Order details UI: loading/error handling, tooltips on key columns.

For **file-level** history, use `git log` on `backend/app/api/stock.py`, `frontend/src/pages/OrderDetails.tsx`, and `docs/ANALYTICS_PROFIT_LOGIC.md`.
