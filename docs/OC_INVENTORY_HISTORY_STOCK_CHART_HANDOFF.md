# Stock chart + movement — handoff for Opus / next engineer

## What the chart uses (current)

**`GET /api/inventory-status/inventory-history`** builds the **Stock level by day** series from **`oc_stock_movement_line`** only (not inventory pull snapshots).

- Filter by active OC connection, **MFSKUID** set from `_resolve_mfsku_list_for_movement` (seller SKU / sku_code / mfskuid / all mapped), optional **service_region**, and **`update_time_utc`** in `[from, to]`.
- **`inventory_status`**: **AVL** only. INTRAN not used in the series.
- **`available` (portfolio “All”)**: **Running total** — seed each `(mfskuid, service_region)` with the **last AVL row before `from`** (`row_number` window). For each distinct `update_time_utc` in range, apply **`MAX(actual_count)`** per `(ts, mfskuid, region)` (put-away bursts), update in-memory state, then **`available` = sum(state)`**. Summing only SKUs that had a row **at** timestamp *T* (without carry-forward) falsely **dropped** the line when the next event touched fewer SKUs.
- **`in_transit`** in JSON is always **0**.

Frontend **`buildDailyStockLevelsFromHistory`** is unchanged: forward-fills per local day from those points.

## Related

- **Movement sync / table:** [`OC_GET_STOCK_MOVEMENT_HANDOFF.md`](./OC_GET_STOCK_MOVEMENT_HANDOFF.md), `POST /sync-stock-movement`, `oc_stock_movement_store.py`.
- **Code:** `backend/app/api/inventory_status.py` — `list_inventory_history`, `_resolve_mfsku_list_for_movement`.
- **Model:** `OCStockMovementLine` in `app/models/settings.py`.
- **Dropped table:** `oc_sku_inventory_history` removed in Alembic **`024_drop_oc_sku_inventory_history`** (revises `023`). Older revisions still mention the old table in history; do not delete old migration files.

## If the chart is empty

Ensure **`oc_stock_movement_line`** has rows in the date range (use **Sync range from OC** / **Incremental sync** on Stock & movement). The chart does not call GetStockMovement by itself.

## If stuck

Paste **`GET /inventory-history`** JSON (`points.length`, `from_date`/`to_date`), movement row count for the same filter, and OC **`inventory_status`** values if they differ from **AVL** / **INTRAN**.
