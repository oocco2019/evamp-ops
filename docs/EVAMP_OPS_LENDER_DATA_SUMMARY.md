# Evamp Ops: data, metrics, and profit logic (standalone reference)

**Audience:** Readers (including other AIs) who have **no access to the codebase or other documents**. Everything needed to understand what Evamp Ops calculates, how profit is derived, and what is out of scope is in this file.

**Product in one sentence:** Evamp Ops imports **eBay** and **Shopify** orders, connects to **OrangeConnex (OC)** for inventory/fulfilment, stores **SKU costs** and **purchase orders**, and exposes **sales analytics** (volume, profit by SKU/country, order-level drill-down), **inventory** views, and related APIs.

---

## Table of contents

1. [Order and sales data (revenue and volume)](#1-order-and-sales-data-revenue-and-volume)
2. [Profit calculation — full specification](#2-profit-calculation--full-specification)
3. [Order details (line-level transparency)](#3-order-details-line-level-transparency)
4. [SKU master data (costs used in profit)](#4-sku-master-data-costs-used-in-profit)
5. [Purchase orders (internal)](#5-purchase-orders-internal)
6. [Inventory and supply chain (OrangeConnex)](#6-inventory-and-supply-chain-orangeconnex)
7. [What this is not (limits for lenders)](#7-what-this-is-not-limits-for-lenders)
8. [Loan or dashboard requirements — suggested mapping](#8-loan-or-dashboard-requirements--suggested-mapping)
9. [Configuration reference (environment)](#9-configuration-reference-environment)
10. [Implementation pointers (for engineers)](#10-implementation-pointers-for-engineers)

---

## 1. Order and sales data (revenue and volume)

- **Channels:** Each order has a **sales channel** (e.g. eBay, Shopify). The same profit **formulas** apply once order rows store marketplace pricing, **payout to seller** (field name: total due to seller, with currency), line items, dates, and ship-to **country**.

- **Cancelled orders** are excluded from profit and from the sales summary used for analytics.

- **Geography:** For filters and country rollups, **Puerto Rico** and **US Virgin Islands** are treated as **US**.

- **Sales summary (time series):** For a date range, the API aggregates **order count** and **units sold**, grouped by **day, week, or month**, with optional filters by **country** and **SKU** (`GET /api/stock/analytics/summary`).

- **Velocity:** For one SKU and a date range, **units sold**, **number of calendar days in the range**, and **units per day** (`GET /api/stock/planning/velocity`). This is historical velocity, not a forecast.

---

## 2. Profit calculation — full specification

Profit is computed **per order** in **GBP**, then **split across line items (SKUs)** for “by SKU” views. The implementation lives in one module (`stock.py`); function names below match the code: `_order_profit_gbp`, `_total_due_seller_gbp_amount`, `_uk_vat_gbp`, `_profit_after_tax`.

### 2.1 Inputs (conceptual)

| Input | Source | Role |
|--------|--------|------|
| **total_due_seller** | Order row (imported from eBay/Shopify) | Marketplace “payout” / money to seller for the order |
| **total_due_seller_currency** | Order row | ISO currency of that payout (if missing, order currency is used) |
| **order_currency** | Order row | Currency of buyer/mirror pricing fields (e.g. `price_total`, `tax_total`) |
| **price_total** | Order order | Order total in `order_currency` (used for UK VAT basis and allocation) |
| **tax_total** | Order row | Tax from marketplace; may be empty on some UK orders |
| **country** | Order row | Ship-to (2-letter); **GB** triggers UK VAT logic |
| **Landed + postage** | **SKU** master: per line, `(landed_cost + postage_price) × quantity` in **USD** | COGS for normal sales |
| **Postage only** | Same SKU fields, `postage_price × quantity` per line, summed | Used in **refund** path for **2× postage** cost |

### 2.2 Converting “money in” to GBP (**td_gbp**)

- If **total_due_seller** is null, **no** profit is calculated for that order in these flows.

- Payout is assumed to be in **total_due_seller_currency**; if that is not set, **order_currency** is used.

- Conversion to **GBP** (result = **td_gbp**), using configurable rates:

  - **GBP** → multiply by **1.0**
  - **EUR** → multiply by **EUR_TO_GBP_RATE** (e.g. 0.86)
  - **Any other** currency code (including **USD**) → multiply by **USD_TO_GBP_RATE** (e.g. 0.79)

- Amounts are rounded to **2 decimal places (pence)** after conversion.

### 2.3 Order total in GBP (**price_gbp**)

- **price_total** (order currency) is converted to GBP with the **same** order-currency→GBP rule as in §2.2. This drives UK VAT when `tax_total` is empty and is used in allocation (§2.7).

### 2.4 COGS in GBP — two regimes

**A) Normal sale — payout in GBP is strictly positive (**td_gbp > 0**)**

- Sum over lines: for each line, **(landed_cost + postage_price) × quantity** in **USD** (from SKU master).

- **Cost (GBP)** = **(that USD sum) × USD_TO_GBP_RATE**.

**B) Refund / clawback — payout in GBP is zero or negative (**td_gbp ≤ 0**)**

- **Business assumption:** Inventory is **returned** and can be resold, so **landed cost is not treated as a loss** in this model.

- **Cost (GBP)** = **2 × (sum of postage_price × quantity in USD) × USD_TO_GBP_RATE** — i.e. **outbound + return** postage only, not landed cost.

- **Note:** “Refund mode” is determined from **td_gbp** (after conversion to GBP), not from the raw string in the database. That matches the implementation.

**UK VAT in refund mode:** **£0** (sale treated as reversed for UK VAT in this model).

### 2.5 UK VAT in GBP (only if ship-to is **GB**)

If country is not **GB**, **VAT (GBP) = 0**.

If country is **GB**:

1. If **tax_total > 0** (marketplace provided tax):  
   **VAT (GBP)** = **tax_total** converted to GBP using the same rate used for **price_total** to GBP (order-currency → GBP).

2. If **tax_total** is **missing or zero:** treat **price_gbp** as **VAT-inclusive** at **UK_VAT_DEFAULT_RATE** (default **0.20**):  
   **VAT (GBP)** = **price_gbp × (rate / (1 + rate))**  
   This **extracts** the tax embedded in a VAT-inclusive price. At 20% it is **not** the same as 20% × gross (which would overstate VAT). At 20%, it is equivalent to **gross / 6** on the VAT-inclusive total.

3. If **td_gbp ≤ 0** (refund path per §2.4B): **VAT (GBP) = 0** regardless of the above.

**UK business narrative (simplified):** eBay may not always send **tax_total** for UK orders. The app either uses marketplace tax or extracts VAT from the inclusive buyer total using the default rate.

**Non-UK formula (gross profit before “profit tax”):**

`gross_profit_gbp = td_gbp - cost_gbp`  
(with **cost_gbp** from §2.4A or B)

**UK formula:**

`gross_profit_gbp = td_gbp - cost_gbp - vat_gbp`

### 2.6 “Displayed” profit (after notional tax on profit)

The UI and SKU rollups show **not** `gross_profit_gbp` but:

**displayed_profit_gbp = gross_profit_gbp × (1 − PROFIT_TAX_RATE)**

Default **PROFIT_TAX_RATE = 0.30** means “take home **70%** of gross profit” in this **simplified** model (it is **not** a full corporation tax computation).

All **“profit”** figures in **by-SKU**, **by-country**, and the **Order details** **net** columns use this after-tax value (unless a screen explicitly says “gross”).

### 2.7 Allocating order profit to SKUs (multi-line orders)

- For each line, define **allocation share** = **line_total / order price_total** (in order currency; ratio is the same in GBP for allocation purposes).

- **Gross** and **net** (after §2.6) order profit are multiplied by that share to get **line gross** and **line net**.

- If **price_total** is **0**, the by-SKU aggregation **skips** the order (cannot allocate).

### 2.8 EUR display

- **profit_eur = profit_gbp_after_tax × GBP_TO_EUR_RATE** (simple translation, not a second ledger).

### 2.9 eBay vs Shopify (payout quality)

- **eBay:** Initial import can use **Fulfillment**-style data. A separate **backfill** endpoint can refresh **payout** (and ad-fee metadata) from **eBay Finances** so “money in” is closer to **net to seller** after platform fees, where the API allows.

- **Shopify:** At import, payout is a **defined proxy** (e.g. order total minus tax, with fallbacks) so the same **td_gbp** pipeline runs. **Shopify** and **eBay** orders are distinguished by **sales channel** in the database.

### 2.10 Historical fixes the logic was designed to handle (transparency)

These are not formulas but **known pitfalls** the rules avoid:

- **Refunds:** Negative or zero **td_gbp** must not use full landed+postage as “lost” when stock is returned; hence **2× postage** and **no UK VAT** on that path.
- **UK zero tax_total:** Using **0** VAT was wrong for many real UK sales; hence **inclusive** extraction with **UK_VAT_DEFAULT_RATE**.
- A generic **2% of order value** fee was **removed** from profit; profit is **payout − COGS (per rules) − UK VAT (per rules)**, then **after-tax** scaling.

### 2.11 When values refresh

- **Orders:** After **eBay/Shopify import** and optional **eBay backfill** (Finances). A scheduled job and manual **import** can refresh data.

- **SKU costs:** Changing **landed** or **postage** in the SKU master changes COGS the next time analytics are computed; there is no separate “lock” of historical COGS in the order row.

### 2.12 Automated tests (profit)

- `backend/tests/test_order_profit_refund.py` — scenarios for **non-UK**, **UK** with inclusive VAT, **UK** with eBay **tax_total**, and **refund** (postage-only cost, no UK VAT on clawback).  
- Command: `pytest backend/tests/test_order_profit_refund.py` (from backend with venv, when the environment runs).

---

## 3. Order details (line-level transparency)

**Purpose:** Aggregates (by SKU, by country) **hide** payout, COGS, VAT, and per-line **allocation**. **Order details** is a **line-level** report so you can reconcile to the marketplace and SKU master.

- **UI route (typical app):** `/order-details` (may be linked from Sales Analytics in the product).

- **API:** `GET /api/stock/analytics/order-details`  
  Query: `from`, `to` (dates), optional `country`, optional `sku` (filters line items).

- **Response:** `rows` (one row per line item, or subset when filtered) and `totals` (sum of line costs, line net/gross, distinct order payout sums, etc.).

**Mental model of columns (aligned with the profit engine):**

| Area | Meaning |
|------|--------|
| Order / marketplace | Order date, marketplace order id, country, line SKU, quantity. |
| Payout | **Due to seller** — amount in **total_due_seller** with currency **total_due_seller_currency** (not always GBP on screen; format with correct ISO currency). |
| Buyer / list side | Buyer total, tax, line total — usually in **order_currency**. |
| GBP bridge | Order total converted to GBP for internal UK VAT and checks. |
| COGS (SKU) | Landed and postage in GBP (USD × rate), with **refund mode** using postage-only and 2× rules as in §2.4. |
| UK VAT (analytics) | The **VAT** used in **profit** may follow §2.5, not a blind copy of empty **tax_total**. |
| Profit | **Order gross / net** and **line gross / net** — order-level from `_order_profit_gbp` and `_profit_after_tax`; line = order × **(line_total / price_total)**. |
| “Tax %” in UI | If shown as **profit tax**, that is **PROFIT_TAX_RATE** on **profit**, **not** the UK VAT rate. |

**How to sanity-check (manual):** Pick one order in the marketplace, compare **payout** and **buyer total/tax** to the row, then recompute **td_gbp − cost − vat** for non-refund, or refund rules for **td_gbp ≤ 0**.

---

## 4. SKU master data (costs used in profit)

- Each **SKU** can store **landed cost**, **postage price**, optional **profit per unit**, and **currency** label. The profit path **uses USD** for **landed + postage** in the current implementation when summing from SKU rows.

- If a line item references a SKU **missing** from the master list, **landed and postage are treated as 0** for that line → **overstated** profit until SKUs are filled in.

---

## 5. Purchase orders (internal)

- **Purchase orders** and **line items** (dates, value, lead time, status, etc.) are supported for **operations** and supplier tracking.

- They are **not** automatically the same as **marketplace COGS** unless the business process ties them; they are a separate data track from **eBay/Shopify P&L** in this app.

---

## 6. Inventory and supply chain (OrangeConnex)

When **OC** is connected (credentials in **Settings** / config), the app can expose:

- **SKU mappings** (seller SKU ↔ OC / fulfilment identifiers) and **inventory** snapshots.  
- **Stock movement** (sync from OC, date ranges, filters).  
- **Inbound orders** (lists, status summaries, stage estimates as implemented).  
- **Inventory history** (availability over time, stockout indication in the series).  
- **Stock forecast** bundle: **burn** vs **on-hand** style metrics using a **documented** method in the API response **note** field (not a full ML forecast — read the **note** in the response).

These support **stock and ops** questions; they are **not** statutory financial statements.

---

## 7. What this is not (limits for lenders)

- **Not** a general ledger, **not** bank reconciliation, **not** full **VAT return** or **statutory** accounts.  
- **Profit** is **management-style** with fixed **FX**, **UK VAT** approximations, and **notional** tax on profit.  
- **Cash** timing (marketplace **payout** dates, holds, chargebacks) is **not** fully modelled.  
- **Order history** depth may be limited by how far back **API imports** are run (e.g. rolling windows on marketplace APIs).  
- **Lenders** should not treat these numbers as **audited** without an accountant and raw source agreements.

---

## 8. Loan or dashboard requirements — suggested mapping

- **Revenue / volume:** Use **summary** (orders, units) and **by channel** if you add channel filters in reporting (data already has `sales_channel`).  
- **Margin / profit:** Reuse the definitions in **§2**; any **new** “EBITDA” or “margin” needs an explicit spec so it does not conflict.  
- **Inventory / working capital:** OC **inbound**, **on-hand**, **movement**, **history**, **forecast** (read API **notes**).  
- **Gaps to plan if the lender wants them:** bank feeds, AR/AP, **DSO**, debt schedule, **covenant** math — **outside** the current app unless new data and modules are added.

---

## 9. Configuration reference (environment)

| Variable | Meaning | Typical example |
|----------|---------|-----------------|
| `USD_TO_GBP_RATE` | Multiply **USD** amounts (SKU costs; non-EUR/GBP order handling where applicable) to get **GBP** | 0.79 |
| `EUR_TO_GBP_RATE` | **EUR** order amounts → **GBP** | 0.86 |
| `PROFIT_TAX_RATE` | Applied to **gross** profit: **displayed = gross × (1 − rate)** | 0.30 |
| `UK_VAT_DEFAULT_RATE` | **GB** orders, when `tax_total` is 0/null: VAT from inclusive **price_gbp** = **× rate/(1+rate)** | 0.20 |
| `GBP_TO_EUR_RATE` | **GBP** profit → **EUR** display | 1.16 |

**Shopify (optional, if not using in-app storage):** `SHOPIFY_SHOP`, `SHOPIFY_ACCESS_TOKEN` — the product can also store credentials encrypted in the database via **Settings → Shopify**.

---

## 10. Implementation pointers (for engineers)

| Concern | Location (repository paths) |
|---------|-----------------------------|
| Profit helpers and analytics APIs | `backend/app/api/stock.py` |
| Config defaults | `backend/app/core/config.py` |
| OC / inventory / forecast | `backend/app/api/inventory_status.py` |
| Order details API models | `OrderDetailRow`, `OrderDetailsResponse`, `get_analytics_order_details` in `stock.py` |
| Profit unit tests | `backend/tests/test_order_profit_refund.py` |
| Order details UI (if present) | `frontend/src/pages/OrderDetails.tsx` |

---

*This file is self-contained. Older split docs in the same `docs/` folder (e.g. `ANALYTICS_PROFIT_LOGIC.md`, `ORDER_DETAILS_AND_ANALYTICS_TRANSPARENCY.md`) may repeat subsets of this content for developers working in-repo.*
