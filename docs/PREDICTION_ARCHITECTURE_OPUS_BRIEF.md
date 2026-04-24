# Brief for Opus: stock run-out prediction architecture (EvampOps)

Paste this whole file when asking Opus to propose a **prediction architecture** (not line-by-line implementation). Repo: **evamp-ops** — FastAPI + PostgreSQL + React.

---

## Product goal

Give sellers an **estimated calendar date when available stock hits zero** (“run out”), with clear assumptions. Primary use case: **SKU-level** (e.g. seller SKU `uke01`), optional **“All SKUs”** rollup later.

Labeling should be explicit, e.g. **“If no inbound restock, estimated OOS ≈ &lt;date&gt;”**.

---

## What already exists (do not re-invent blindly)

1. **Stock & movement UI** (`frontend/src/pages/InventoryMovement.tsx`)  
   - **Stock level by day** chart: AVL-only time series derived from **`oc_stock_movement_line`** via **`GET /api/inventory-status/inventory-history`**.  
   - **Stored movement lines** table: **`GET /api/inventory-status/stock-movement`**.  
   - Sync: **`POST /api/inventory-status/sync-stock-movement`** (OC GetStockMovement → DB). OC exposes roughly **last 12 months** per request; persisted rows stay in PostgreSQL.

2. **Reference docs in repo**  
   - **`docs/STOCK_CHART.md`** — how the chart is built (running sum across SKU/region, `MAX` per burst second, `COALESCE(update_time_utc, created_at)`, AVL only).  
   - **`docs/OC_GET_STOCK_MOVEMENT_HANDOFF.md`** — OC movement API, windows, scheduler.

3. **Other data**  
   - **Sales / orders** exist in the app (eBay import, Sales Analytics–style aggregates). Likely better **demand signal** than inferring burn rate only from inventory slope.  
   - **Current OC inventory** via **`GET /api/inventory-status/inventory`** (snapshot after “Pull latest”).

---

## Why “chart slope alone” is insufficient

- Inventory series is **sawtooth**: restocks create **jumps**. Burn rate must use a **depletion segment** (after last inbound/put-away) or **external sales velocity**.  
- Chart points are **event-driven**; daily series is **forward-filled** — quiet periods may not mean zero sales.  
- Chart uses **AVL** movement lines only; **INTRAN/RCVD** are separate buckets.

---

## Constraints and non-goals (unless product expands)

- No requirement to predict **inbound** (POs, OC receipts) unless you add data.  
- **Uncertainty** should be first-class (intervals, “low confidence if restock &lt; 7d ago”).  
- Must stay honest when **movement history** or **sales history** is sparse.

---

## What to ask Opus to deliver

1. **Recommended signal(s)** for daily “burn”: trailing sales from orders vs. inferred from AVL deltas vs. hybrid; how to handle **post-restock** windows.  
2. **Data model / API shape**: e.g. new endpoint vs. extending inventory-history; caching; SKU vs. connection scope.  
3. **Algorithm tiers**: MVP (linear days-of-cover) vs. richer (seasonality, confidence bands).  
4. **Edge cases**: new SKU, promotional spikes, multi-region same seller SKU, “All SKUs” aggregation definition.  
5. **UI contract**: what the frontend shows (single date vs. range, disclaimers, refresh cadence).

---

## Stack reminder

Backend: **FastAPI**, **SQLAlchemy**, **PostgreSQL**. Frontend: **React**, **TanStack Query**, **Recharts**. OrangeConnex is external; eBay orders are in-app.

---

*End of brief.*
