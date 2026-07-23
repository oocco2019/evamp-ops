# Stock Order – behaviour and decisions

UI copy on the Stock Order page is kept minimal. Details that used to appear as on-page blurbs live here.

## Purpose

Plan how many units to order per SKU, estimate cost and profit, then:

- **Generate supplier order** – message / order text for the supplier  
- **Generate OC inbound** – OrangeConnex SKU import Excel workbooks  
- **Fill units from OC stock** – seed units from OrangeConnex available + in transit  
- **Copy plan to clipboard** / **Clear all**

## Units and cost

- Enter **units** per SKU in the table. Values are saved automatically in **this browser** (`localStorage` key `evampops.stockPlanning.unitsBySku`).
- **Landed cost** on each SKU is in **USD**.
- Line / total cost:
  - **USD** = `landed_cost × units`
  - **GBP** = USD ÷ **1.35** (fixed `USD_PER_GBP` in `StockPlanning.tsx`; not the backend `USD_TO_GBP_RATE`)

## Est. profit (GBP)

- **Profit lookback (Sales Analytics)** dropdown (30 / 90 / 180 / 365 days) controls the window for realized avg profit per unit.
- Prefer: `planned units ×` average profit/unit from that window, using the **same logic as Sales Analytics → by SKU** (`GET /api/stock/analytics/by-sku`). See [ANALYTICS_PROFIT_LOGIC.md](ANALYTICS_PROFIT_LOGIC.md).
- If a SKU has **no sales** in the window: fall back to the **manual SKU profit field × 0.8**.

## Items per carton

- Control label in UI: **Items per carton for Generate supplier order**.
- Value is used when splitting each SKU’s planned quantity into **carton rows** for exports (currently fixed at **4** in code / storage).
- **Generate OC inbound** also splits quantities into carton rows using this value.

## Generate OC inbound

Downloads OrangeConnex SKU import files (template `SKUImportTemplateV1_EN.xlsx`):

- One workbook per **SKU letter-prefix group** (e.g. `bee01` & `bee02` same file; `dee01` another).
- Columns use **seller SKU** and OC **MFSKUID** from Inventory status mappings.
- Groups with **no units** are skipped.
- Each SKU quantity is split into carton rows from **Items per carton**.
- Multiple groups download as a **zip**.

Implementation: `frontend/src/utils/ocSkuImportExport.ts`, triggered from `StockPlanning.tsx`.
