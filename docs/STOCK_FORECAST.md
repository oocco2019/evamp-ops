# Stock run-out forecast

How the **Stock run-out forecast** table on **Stock & movement** (`InventoryMovement.tsx`) is computed. For the daily stock chart and movement sync, see [`STOCK_CHART.md`](./STOCK_CHART.md).

---

## UI

**Route:** Stock & movement → table above the chart.

| Column | Meaning |
|--------|---------|
| **SKU** | `sku_code` from OC mapping, else seller SKU id |
| **Available** | Latest **AVL** `actual_count` from `oc_stock_movement_line` |
| **Ordered** | Available + **in transit** + **received** from `oc_sku_inventory` (last OC snapshot pull) |
| **Burn rate/day** | Average eBay units sold per in-stock day in the selected period (see below) |
| **Ordered run-out** | `ordered ÷ burn rate` as days, plus calendar date (colour: red &lt; 14d, amber ≤ 30d, green &gt; 30d) |
| **Reorder** | Suggested order qty and **order-by date** (90-day supplier lead time before run-out). Overdue rows show **Order now** in red. Sortable. |

Rows are sorted by **shortest ordered run-out first** on the server; click any column header to re-sort (same pattern as Sales Analytics — ▲/▼ indicator, preference saved in `localStorage`).

The table **uses the same From / To filter** as the stock chart (period presets or custom dates). Changing the filter refetches `GET /api/inventory-status/stock-forecast?from=…&to=…`.

Subtitle under the table repeats the formula from the API `note` field.

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
- If ordered stock is **0** but historical in-stock sales produce a burn rate, days of cover is **0** and the SKU is treated as already at run-out so reorder guidance shows **Order now**.

**Assumption:** no further inbound restock after today (in-transit and received are counted once in **Ordered**, not double-counted when they become available).

---

## Reorder (90-day lead time)

Supplier delivery is assumed **90 calendar days** after placing the order (`REORDER_LEAD_TIME_DAYS` in `stock_forecast.py`).

| Field | Formula |
|-------|---------|
| **Order-by date** | `ordered run-out date − 90 days` |
| **Suggested qty** | `ceil(burn_rate × 90)` units (covers sales over the lead window; arrival timed to ordered run-out) |

Example: ordered run-out **1 Dec 2026** at 2 units/day → reorder by **2 Sep 2026**, qty **180**.

If the order-by date is **today or earlier**, the UI shows **Order now** (red). Amber when within 30 days.

---

## Implementation

| Piece | Location |
|-------|----------|
| Core logic | `backend/app/services/stock_forecast.py` |
| API | `GET /api/inventory-status/stock-forecast` in `backend/app/api/inventory_status.py` |
| Frontend | `frontend/src/pages/InventoryMovement.tsx`, `inventoryStatusAPI.getStockForecast` |
| Tests | `backend/tests/test_stock_forecast.py` |

---

## Tests

```bash
docker compose exec backend python -c "import pytest; pytest.main(['tests/test_stock_forecast.py','-q'])"
```

(or run on host if pytest is installed in the backend venv)

Covers `average_burn_rate`, `forward_fill_daily_avl`, `forecast_note`, `_cover_and_oos`.

---

## Related docs

- [`STOCK_CHART.md`](./STOCK_CHART.md) — daily AVL chart, movement sync, forward-fill rules
- [`PREDICTION_ARCHITECTURE_OPUS_BRIEF.md`](./PREDICTION_ARCHITECTURE_OPUS_BRIEF.md) — future ideas (seasonality, confidence bands); not implemented in the current table
