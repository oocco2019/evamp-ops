# Stock chart and movement data

This document describes how **Stock level by day** and **Stored movement lines** work in EvampOps: data sources, APIs, aggregation rules, sync, and troubleshooting. For OrangeConnex **GetStockMovement** HTTP details and OC error behaviour, see [`OC_GET_STOCK_MOVEMENT_HANDOFF.md`](./OC_GET_STOCK_MOVEMENT_HANDOFF.md).

---

## 1. What you see in the UI

**Route:** Stock & movement (`InventoryMovement.tsx`).

| Area | What it shows |
|------|----------------|
| **Filters** | Period presets, **From / To**, **SKU** (All or seller SKU from mappings). Same card pattern as Sales Analytics. |
| **Stock level by day** | Line chart (Recharts): **Available** only — one series, blue (`#3b82f6`). INTRAN was removed from the chart (unreliable / not needed). |
| **Daily table** under the chart | Same daily series as the chart: local calendar day, forward-filled **available**. |
| **KPI tiles** | Current stock from **`GET /inventory-status/inventory`** (last OC snapshot pull), filtered by SKU when not All. |
| **Stored movement lines** | Raw rows from PostgreSQL **`oc_stock_movement_line`** (same date/SKU filters as the chart queries). |

The chart does **not** call OrangeConnex live. It reads **only** what is already in **`oc_stock_movement_line`**.

---

## 2. Data source: `oc_stock_movement_line`

Movement rows are written by **`POST /api/inventory-status/sync-stock-movement`** (and the scheduler’s incremental pull). OC’s **GetStockMovement** response is flattened and upserted by **`movement_id`** (`oc_stock_movement_store.py`).

Important columns:

| Column | Role |
|--------|------|
| `connection_id` | Active OC connection. |
| `mfskuid`, `service_region` | SKU / region slice. |
| `inventory_status` | OC bucket code, e.g. **AVL** (available), **INTRAN**, **RCVD**, **RSVALOC**. |
| `quantity` | Delta for that line. |
| `actual_count` | Running **after** count for that line’s status (OC’s meaning). |
| `update_time_raw` | Verbatim OC time string. |
| `update_time_utc` | Parsed UTC **naive** datetime when parsing succeeds. |
| `created_at` | Row insert time (server). |

If OC’s time string **does not parse**, `update_time_utc` is **NULL**. Reads must not drop those rows (see §5).

The old table **`oc_sku_inventory_history`** was removed; the chart **never** used inventory pull snapshots for the current design. Alembic **`024_drop_oc_sku_inventory_history`** drops that table if present.

---

## 3. APIs

### 3.1 `GET /api/inventory-status/inventory-history`

**Purpose:** Time series for the stock chart (`InventoryHistorySeriesResponse`: `points[]` with `recorded_at`, `available`, `in_transit` always `0`, `stockout`).

**SKU scope:** `_resolve_mfsku_list_for_movement` — optional `seller_skuid` (case-insensitive), `sku_code`, `mfskuid`, or **all mapped SKUs** when none of those are set.

**Status:** Only **`inventory_status`** with **`UPPER(...) = 'AVL'`**. INTRAN / RCVD / etc. are **not** part of this series.

**Event time:** **`event_t = COALESCE(update_time_utc, created_at)`** — any filter or ordering uses this so unparsed OC times still participate.

**Aggregation (Available, “All” and single-SKU):**

1. **Seed** (before `from` date): For each `(mfskuid, service_region)`, take the **latest** AVL row with `event_t < start_of_range` (SQL window: `row_number` partitioned by mf+region, order by `event_t` desc). Build a map **state[(mf, region)] → last actual_count** (coalesced to int).

2. **In-range bursts:** Group AVL rows by **`(event_t, mfskuid, service_region)`** and take **`MAX(actual_count)`** — many lines can share the same second (e.g. put-away +4 steps); each line’s `actual_count` is a running “after” value, so **summing** them was wrong (inflated spikes, e.g. ~242 vs ~123).

3. **Walk** distinct `event_t` in ascending order. For each time, apply all burst updates for that second to **state**, then set **`available = sum(state.values())`**.

This **carry-forward** fixes the bug where **summing only rows at timestamp T** made the total **collapse** when the next event touched **fewer SKUs** (next line only updated one SKU; others were omitted from the sum).

**Response `note`:** Short human-readable summary of behaviour (may change slightly over time).

### 3.2 `GET /api/inventory-status/stock-movement`

**Purpose:** Full movement table on the same page.

**Filters:** Same MFSKUID resolution as above; **`event_t = COALESCE(update_time_utc, created_at)`** between **from** and **to** (calendar day bounds → start of day / end of day naive on server).

**Order:** `event_t` ascending, then `id`.

**Limit:** `line_limit` (default large); may truncate oldest segment if over limit.

---

## 4. Frontend

**File:** `frontend/src/pages/InventoryMovement.tsx` — React Query for `getInventoryHistory`, `listStockMovement`, `listInventory`.

**Daily series:** `buildDailyStockLevelsFromHistory` in **`frontend/src/utils/inventoryHistoryFormat.ts`**: for each **local calendar day** in `[from, to]`, set **available** to the last sample whose `recorded_at` is on or before **end of that day** (forward-fill). Ensures the X-axis spans the full filter even when OC events are sparse.

**API client:** `frontend/src/services/api.ts` — `getInventoryHistory`, `listStockMovement`.

---

## 5. Why `COALESCE(update_time_utc, created_at)`?

`parse_oc_update_time_to_utc` in **`oc_stock_movement_store.py`** only accepts strings it can parse. Bad or unusual OC formats leave **`update_time_utc` NULL**.

Previously, list endpoints required **`update_time_utc IS NOT NULL`**, so those rows **never appeared** in any date range — empty table/chart despite thousands of rows in the DB.

Using **`created_at`** as a fallback places the row on the timeline when the app stored it (approximate, not the true OC event time, but better than invisible).

---

## 6. Sync and OC limits

- Data enters PostgreSQL via **`sync-stock-movement`** (manual **Sync range** / **Incremental** on the page, or scheduler).
- OC typically allows only about the **last 12 months** of movement queries; older windows may be **clamped** (see sync response and [`OC_GET_STOCK_MOVEMENT_HANDOFF.md`](./OC_GET_STOCK_MOVEMENT_HANDOFF.md)).
- Rows already stored are **not** TTL-deleted by this app; long history depends on **running syncs** before events fall outside OC’s window.

---

## 7. Code map

| Piece | Location |
|-------|----------|
| `list_inventory_history`, `list_stock_movement`, `_resolve_mfsku_list_for_movement` | `backend/app/api/inventory_status.py` |
| Persist movement lines | `backend/app/services/oc_stock_movement_store.py` |
| OC fetch / clamp | `backend/app/services/oc_client.py` (see movement handoff doc) |
| Model | `backend/app/models/settings.py` — `OCStockMovementLine` |
| Chart + table UI | `frontend/src/pages/InventoryMovement.tsx` |
| Daily bucketing tests | `frontend/src/utils/inventoryHistoryFormat.test.ts` |

---

## 8. Troubleshooting

| Symptom | Things to check |
|--------|-------------------|
| Chart/table **empty** for a range | **From/To** actually overlaps when events exist (e.g. **Today** only has no lines if nothing moved today). Run **Sync range** for that window. Confirm **`oc_stock_movement_line`** row count for the connection. |
| **Debug JSON** shows many rows but UI empty | Was often **NULL `update_time_utc`** before **coalesce** fix; ensure deployed backend includes **`COALESCE(..., created_at)`**. |
| Spike then cliff (historical bugs) | Fixed: **sum** of burst `actual_count` at same second; **sum at T** without carry-forward. Current logic is §3.1. |
| “All” vs one SKU | **All** sums **carried-forward** levels across mapped MFSKUIDs; one SKU filters mappings for that seller SKU. |

---

## 9. Related documentation

- [`OC_GET_STOCK_MOVEMENT_HANDOFF.md`](./OC_GET_STOCK_MOVEMENT_HANDOFF.md) — OC API, 12-month window, 7-day chunks, 502s, scheduler.
