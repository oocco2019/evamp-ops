# Data retention audit

**Principle:** EvampOps is the permanent system of record for data pulled from eBay, Shopify,
and OrangeConnex (OC). Those platforms purge data after a limited window; the owner needs this
data queryable 10+ years out. See the always-applied rule `.cursor/rules/data-retention.mdc`.

This document records what is durably persisted today, and the known gaps where data we receive
is *not* fully retained. Keep it updated when ingestion changes.

## Durably persisted (safe)

| Data | Table(s) | Pattern | Notes |
| --- | --- | --- | --- |
| eBay/Shopify orders | `orders`, `line_items` | Upsert by `(sales_channel, ebay_order_id)` | Retained indefinitely. Re-import updates mutable fields (e.g. `cancel_status`). Full raw order JSON kept in `orders.raw_payload` (incl. line items). |
| Customer messages | `messages`, `message_threads` | Append, never purged | Explicitly retained after eBay deletes them. Only `stub-%` rows are cleaned. |
| Message attachments | `message_media_blobs` | Bytes stored on sync | Gold-standard pattern: we keep the actual file bytes after eBay purges the URL. |
| OC stock movements | `oc_stock_movement_line` | Append-only ledger (upsert by `movement_id`) | Immutable event log; **source of truth for stock-over-time**. Not TTL-pruned. |
| OC inbound orders | `oc_inbound_orders` | Upsert by `(connection, dedup_key)` | Keeps `raw_payload` of the latest sync + persisted stage estimates. |
| SKUs, POs, warehouses, templates, AI learning | various | Retained | User-owned config/records. |

## Resolved

1. **Order raw payloads — DONE (migration 025).** `orders.raw_payload` (JSON, nullable) now stores
   the complete marketplace order object as received — eBay Fulfillment order / Shopify order,
   **including its line items**. Captured at the parse layer (`parse_orders_to_import` in
   `ebay_client.py`, `parse_shopify_order_to_import` in `shopify_client.py`) and persisted via the
   shared `_parsed_order_to_orm_payload`. Cost is a few KB per order (negligible). Scope note:
   incremental import only re-fetches changed orders, so `raw_payload` backfills for new/changed
   orders and the last-90-day full import; orders that predate this change and never change again
   keep their mapped columns but won't get a raw backfill (they are already past the platform's
   retention window).

## Remaining gaps (lower priority)

2. **`oc_sku_inventory` stores only the latest snapshot (overwrite by `mfskuid+region`).**
   Point-in-time stock levels are not snapshotted. The dedicated history table
   `oc_sku_inventory_history` was added (021/023) then **dropped** (024) because the stock
   chart reads the movement ledger instead. This is acceptable *only* because
   `oc_stock_movement_line` is append-only and can reconstruct levels over time — but it makes
   that ledger's completeness load-bearing (see gap 3).

3. **Movement ledger first-backfill is clamped to 365 days** (`clamp_oc_movement_query_bounds`
   in `backend/app/services/oc_client.py`). Movements older than 365 days before the first
   sync were never captured and cannot be recovered. Going forward, regular syncing keeps the
   ledger complete; a long sync gap loses the in-between window permanently.

4. **OC SKU mappings and inventory are deleted and re-synced on reconnect**
   (`delete(OCSkuMapping)` / `delete(OCSkuInventory)` in `backend/app/api/inventory_status.py`,
   ~line 1115). The per-mapping `raw_payload` is lost on re-sync. Low impact (mappings are
   re-fetchable), but it is a delete of received data.

5. **eBay Finances transactions are aggregated, not stored line-by-line.** Only fee totals and
   `ad_fees_breakdown` survive; the full transaction list returned by the Finances API is not
   persisted.

## Recommended priority for remaining gaps

1. Gap 3 — ensure scheduled OC movement sync runs reliably so the ledger never has holes
   (currently handled by the inventory refresh scheduler + full-sync catch-up).
2. Gaps 4, 5, 2 — low impact; deferred. They add complexity/space for little marginal recovery
   value, so left as-is unless a concrete need arises.
