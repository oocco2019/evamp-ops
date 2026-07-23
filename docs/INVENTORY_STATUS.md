# Inventory

UI: `/inventory` → `frontend/src/pages/InventoryStatus.tsx` (embeds `StockMovementPanel` from `InventoryMovement.tsx`).

Old routes `/inventory-status` and `/inventory-movement` redirect to `/inventory`.

On-page explanatory blurbs and the **Inbound orders by status** chart/table were removed; behaviour is documented here. Stock chart / forecast / burn trend details: [`STOCK_CHART.md`](./STOCK_CHART.md), [`STOCK_FORECAST.md`](./STOCK_FORECAST.md).

## Page layout (current)

1. **Inventory** title  
2. **Pull latest data** button  
3. **Filters** (period / SKU for charts & forecast)  
4. **Stock run-out forecast**  
5. **Inbound orders** table (UK/DE/US/AU, ~6 months)  
6. Burn rate trend → stock level chart → KPI tiles → stored movement lines  
7. **SKU mappings**

## Pull latest data

Single blue button under the page title. Same idea as the scheduled job, plus a ~1 year OC movement pull so charts/forecast fill:

- eBay orders (incremental)  
- OC SKU mappings + inventory snapshot  
- **OC stock movement** for ~last year (OC may clamp to ~12 months)  
- Inbound cache (**incremental** `syncInboundOrders(false)`)

The backend also runs an incremental inventory refresh on a schedule (default every **15** minutes; `INVENTORY_REFRESH_INTERVAL_MINUTES`, `0` to disable).

Separately, the backend runs a **full inbound catch-up** twice daily (07:00 / 13:00 Europe/Vilnius) when the API is up. There is no Full backfill button in the UI anymore; use `POST /api/inventory-status/inbound-orders/sync?full=true` only if you wipe the DB or need a one-off rebuild.

**Sold** columns on the inventory table use the same inclusive day windows as Sales Analytics (30 / 90 days).

## Inbound orders (detail table)

- Workflows use OC marketplaces together: **UK**, **DE**, **US**, **AU**.  
- Rows from the **local inbound cache** (last ~6 months by date). Refresh via **Pull latest data** (or the schedulers above).  
- Create / putaway / arrived are parsed on the server from the cache.  
- **CREATE TIME** = first-seen sync timestamp in EvampOps; editable (same date input style as ETA); edited values stay local (not overwritten by later syncs).  
- **Tracking #** from OC `trackingList` when available; click **—** to add your own (saved on the server, not overwritten by OC sync).  
- **ETA** defaults to effective create date + 3 months; overrides saved in this browser (green background). When not overridden, ETA recalculates if create/server dates change.  
- **Courier**: OC carrier links when available; custom tracking URL (server-saved, shown as **Custom**); else parcelsapp.com with country hint from region/warehouse.  
- **Order time (d)** = whole days from effective create to arrived when API includes arrival; else —.  
- **ETA Δ (d)** = whole days from effective ETA to arrived (arrived − ETA).  
- Click column headers to sort. Click **SKU count** to keep only orders with SKU count ≥ 5 (mint highlight like edited ETA).

## Removed UI

- Page subtitle: “Read-only OrangeConnex visibility inside the platform.”  
- Long helper paragraphs next to Pull latest and under Inbound orders (content preserved above).  
- **Inbound orders by status** pie chart + summary (status distribution); status filtering remains on the Inbound orders table header.  
- **Sync from OC** / **Full backfill (2024+)** buttons (covered by Pull latest + scheduled full catch-up).  
- **Refresh** / **Sync range from OC** / **Incremental sync** in stock Filters (replaced by the single page **Pull latest data**).
- **OC inventory snapshot** table (sold 1m/3m now on Stock run-out forecast).
