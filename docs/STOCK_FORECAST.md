# Stock run-out forecast

How the **Stock run-out forecast** table on **Inventory** (`StockMovementPanel` in `InventoryMovement.tsx`, embedded under Inbound orders) is computed. For the daily stock chart and movement sync, see [`STOCK_CHART.md`](./STOCK_CHART.md).

---

## UI

**Route:** `/inventory` → Stock run-out forecast (below Inbound orders; above burn trend / chart).

| Column | Meaning |
|--------|---------|
| **SKU** | `sku_code` from OC mapping, else seller SKU id |
| **Available** | Latest **AVL** `actual_count` from `oc_stock_movement_line` |
| **Ordered** | Available + **in transit** + **received** from `oc_sku_inventory` (last OC snapshot pull) |
| **Sold last 3 months / 1 month** | eBay units on non-canceled orders over last 90 / 30 **complete** days (through yesterday); same windows as the former OC inventory snapshot columns |
| **Burn rate/day** | Average eBay units sold per in-stock day in the selected period (see below) |
| **Ordered run-out** | `ordered ÷ burn rate` as days, plus calendar date (colour: red &lt; 14d, amber ≤ 30d, green &gt; 30d) |
| **Reorder** | Suggested order qty and **order-by date** (configurable lead; default 90 days before run-out). Overdue rows show **Order now** in red. Sortable. |

Rows are sorted by **shortest ordered run-out first** on the server; click any column header to re-sort (same pattern as Sales Analytics — ▲/▼ indicator, preference saved in `localStorage`).

The table **uses the same From / To filter** as the stock chart (period presets or custom dates). Changing the filter refetches `GET /api/inventory-status/stock-forecast?from=…&to=…`.

**On-page copy:** “Days with less than 7 units are ignored.” (in-stock days for burn use AVL ≥ 7).

**Row selection:** click rows to mark SKUs; the indigo bar shows count + total reorder cost in GBP (SKU landed cost USD × rate). Clear resets the selection.

### Removed UI copy

> AVL = OrangeConnex available stock (actual_count in the AVL bucket). Available and the chart use that value; INTRAN is omitted.

(Full AVL semantics still in [`STOCK_CHART.md`](./STOCK_CHART.md).)

### Removed UI copy (API note; still true; see sections below)

API `note` from `forecast_note()` (still on the JSON response, not shown in UI):

> Burn rate = average eBay units/day over in-stock days (AVL >= 7) from `{from}` to `{to}`. Ordered = available + in transit + received (OC snapshot); ordered run-out = ordered ÷ burn rate; reorder = order 90 days before run-out (qty ≈ burn × 90 days). Assumes no inbound restock.

---

## Burn rate

1. **Window:** filter `from` → `to` (inclusive calendar days).
2. **In-stock days:** days in that window where forward-filled AVL ≥ **7** (from movement history, same logic as the chart).
3. **Sales:** sum of eBay `line_items.quantity` on non-canceled orders whose `order.date` is each in-stock day; SKUs matched via OC mapping (`sku_code` and `seller_skuid`).
4. **Burn rate** = total units sold on those in-stock days ÷ number of in-stock days (simple average, not weighted).

If there are no sales in the sample, burn rate is blank (`—`) and ordered run-out is blank.

---

## Ordered run-out

- **Ordered** = current available + in transit + received (still forecasts run-out when available is 0 but inbound/received stock exists).
- **Days of cover** = `ordered_total / burn_rate_per_day`
- **Est. date** = today + `ceil(days of cover)` calendar days

**Assumption:** no further inbound restock after today (in-transit and received are counted once in **Ordered**, not double-counted when they become available).

---

## Reorder (configurable lead time)

Supplier lead = `STOCK_REORDER_LEAD_TIME_DAYS` (default **90**) + `STOCK_REORDER_BUFFER_DAYS` (default **0**). Effective lead is used for both the run-out forecast table and the burn-rate trend table.

| Field | Formula |
|-------|---------|
| **Order-by date** | `ordered run-out date − effective lead days` |
| **Suggested qty** | `ceil(burn_rate × effective lead)` units |

Example with lead 90: ordered run-out **1 Dec 2026** at 2 units/day → reorder by **2 Sep 2026**, qty **180**.

If the order-by date is **today or earlier**, the UI shows **Order now** (red). Amber when within 30 days.

---

## Burn rate trend comparison

Second table on **Inventory** (**below** the run-out forecast).

**End date:** always **yesterday** (latest complete calendar day — same as `latest_complete_day` / `latestCompleteDayIso`). The page From/To filter does **not** affect this table.

`GET /api/inventory-status/stock-burn-trend`

**UI columns:** SKU · burn30 · burn90 · burn180 · Trend.

| Field | Meaning |
|--------|---------|
| burn30 / burn90 / burn180 | eBay units ÷ in-stock days (AVL ≥ 7) over trailing inclusive 30 / 90 / 180 days ending yesterday |
| Trend | If 30-day units sold ≥ **15**: **Accelerating** (ratio burn30/burn180 &gt;1.25), **Stable** (0.80–1.25), **Decaying** (&lt;0.80). If only 90-day volume clears 15: **insufficient volume**. **low sample** when in-stock days &lt; 60% of the chosen window length |

### Removed UI caption

> Trailing 30 / 90 / 180 days ending at `{yesterday}`. Burn = eBay units ÷ in-stock days (AVL ≥ 7). Volume gate 15 units; low sample when in-stock days &lt; 60% of the chosen window.

API still returns Available, Ordered, ratio, cover, reorder fields for debugging; they are not shown in the table.

**Dead SKUs:** rows with available = 0, ordered = 0, and no burn in any window are hidden by default; **Show dead SKUs** toggles them (preference in `localStorage`). Known inactive examples (docs only, not a force-hide list): `aue01`, `aue02`, `aue04`, `dee91`, `dee92`, `des01`.

Implementation: `backend/app/services/stock_burn_trend.py`, tests in `tests/test_stock_burn_trend.py`.

---

## Implementation

| Piece | Location |
|-------|----------|
| Core logic | `backend/app/services/stock_forecast.py`, `backend/app/services/stock_burn_trend.py` |
| API | `GET /api/inventory-status/stock-forecast`, `GET /api/inventory-status/stock-burn-trend` |
| Frontend | `frontend/src/pages/InventoryMovement.tsx`, `inventoryStatusAPI.getStockForecast` / `getStockBurnTrend` |
| Config | `STOCK_REORDER_LEAD_TIME_DAYS`, `STOCK_REORDER_BUFFER_DAYS` in `backend/app/core/config.py` |
| Tests | `backend/tests/test_stock_forecast.py`, `backend/tests/test_stock_burn_trend.py` |

---

## Tests

```bash
docker compose exec backend python -c "import pytest; pytest.main(['tests/test_stock_forecast.py','tests/test_stock_burn_trend.py','-q'])"
```

(or run on host if pytest is installed in the backend venv)

Covers burn averages, forward-fill, cover, reorder lead, volume gate, bands, low sample, divergence, overstocked, dead-row predicate.

---

## Related docs

- [`STOCK_CHART.md`](./STOCK_CHART.md) — daily AVL chart, movement sync, forward-fill rules
- [`PREDICTION_ARCHITECTURE_OPUS_BRIEF.md`](./PREDICTION_ARCHITECTURE_OPUS_BRIEF.md) — future ideas (seasonality, confidence bands); not implemented in the current table
