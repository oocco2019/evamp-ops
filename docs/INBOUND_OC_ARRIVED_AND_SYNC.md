# Inbound orders: OC sync, “Arrived / Putaway” times, and EvampOps estimates

This document records **what the code does and why**, so future changes do not repeat dead ends (false “arrived today”, merge-only fixes when OC omits data, etc.).

---

## Problem we were solving

- The **Inventory Status** inbound table shows **CREATE TIME**, **Arrived**, **Putaway**, **Order time (d)**, **ETA Δ (d)**.
- **OrangeConnex (OC)** is the source of truth for inbound lifecycle, but:
  - The **partner API** often returns a **thinner** payload than the **OC web portal** (no `batchList`, no `arrivalTime` / `putAwayTime` in verified captures).
  - So **“Arrived”** cannot always match the portal; showing **`--`** can be **correct** when OC JSON has no arrival fields.

---

## What we verified (important)

For at least one real order (`OCI5DE07295030`), a **verbatim** response from **`POST /openapi/3pp/inbound/v1/detail`** (no merge) contained **SKUList**, **trackingList**, **status**, etc., but **no** `batchList` or arrival/putaway **timestamps** in the JSON.

**Conclusion:** Missing **Arrived** in EvampOps is often **not** a bug in our merge flattening alone; the **partner API may not expose** the same dates as the portal. Vendor clarification may be needed for true historical arrival times.

Details and a sample payload live in **`docs/HANDOVER_INBOUND_OC_DETAIL_FINDINGS_OPUS.md`**.

---

## Behaviour summary (current design)

### 1. Where display times come from

Server-side **`_extract_inbound_ui_times()`** in `backend/app/api/inventory_status.py`:

1. Prefer **OC raw JSON** (`raw_payload`): explicit arrival / putaway / batch fields where present.
2. Optional **proxy**: if **Arrived** is still empty but OC gave a **real** putaway timestamp from JSON (`putaway_from_raw`), and status looks like putaway, **Arrived** can mirror that **raw** putaway time (not DB guess).
3. **EvampOps DB estimates** (`putaway_at`, `arrived_at` on `OCInboundOrder`) are used **only** when **eligibility** holds (see below) and **status routing** matches (see below). They represent **when EvampOps first saw** a transition, not the warehouse’s unknown historical clock.

### 2. Eligibility: “first seen since yesterday” (UTC)

**`_eligible_for_inbound_stage_estimates(now, first_seen)`** is true when:

- `first_seen` is **`COALESCE(inbound_at, synced_at)`** (EvampOps first-seen), and  
- `first_seen >=` **start of yesterday** in the **UTC** calendar sense  
  (`datetime.combine(now.date() - 1 day, midnight)`).

**Why:** Older rows should not get **new** sync-clock stamps that read as fake “today” or rewrite history. “Yesterday onward” matches the product rule: apply EvampOps-observed times only for **recent** cache rows.

This gate is used for:

- **Writing** `putaway_at` / `arrived_at` on sync (`_upsert_inbound_rows`), and  
- **Showing** those columns in the UI when OC omits timestamps (same helper conceptually).

### 3. Status routing when OC omits times (but row is eligible)

When OC does not supply the relevant timestamp, DB estimates are mapped as follows:

| Status pattern | Helper | Putaway column | Arrived column |
|----------------|--------|----------------|----------------|
| Arrived-like | `_status_indicates_arrived` | OC / DB rules as today | `arrived_at` or fallback `putaway_at` |
| Putaway-like (incl. partial put away, inbound complete, goods received, etc.) | `_status_indicates_putaway` | `putaway_at` | **Not** filled from DB estimates alone (avoids double-counting; raw putaway proxy still applies when OC sent a real putaway time) |
| Other warehouse (e.g. processing, sorting, QC — not in-transit/cancel) | `_status_indicates_other_warehouse` | OC only | `arrived_at` or `putaway_at` → **Arrived** only |

**Why:** Matches the product rule: **arrived** vs **putaway** statuses map to the right column; anything else that still means “warehouse activity” gets a single synthetic **arrival** time when OC is silent.

### 4. First insert of a new inbound row

New rows **no longer** set `putaway_at` / `arrived_at` to **`utcnow()`** on first insert if the order is already terminal. Those fields stay **NULL** until OC provides data or a **later sync** observes a transition (with eligibility + `_should_set_*`).

**Why:** Avoid stamping **“today”** on orders that were actually completed months ago on first cache.

---

## OC sync pipeline (high level)

In **`backend/app/services/oc_client.py`** → `oc_fetch_inbound_orders`:

1. **List:** `POST /openapi/3pp/inbound/v1/query` (time window, chunked in ≤7-day slices).
2. **Detail by OC number:** `POST /openapi/3pp/inbound/v1/detail` with `inboundNumberList`, merge into `raw_payload` via **`_merge_inbound_list_and_detail`** (shallow dict merge; detail wins per key).
3. **Detail by seller reference:** Second pass when the row has a SKU list **but** no **`batchList`** (arrival times often live under batch in some tenants).
4. **Labels:** separate call; merged as `ocLabelQuery`.

**Why two detail passes:** Some tenants return fuller JSON when queried by seller number instead of OC inbound number.

---

## Diagnostics

- **`GET /api/inventory-status/inbound-orders/lookup?oc_inbound_number=…`** — cached row + derived `create_time` / `putaway_time` / `arrived_time` + `raw_oc_payload`.
- **`GET /api/inventory-status/debug/inbound-detail-raw?oc_inbound_number=…`** — **one** OC detail call, **no merge**; returns verbatim `raw_response`. **Gated** by **`ALLOW_OC_INBOUND_DETAIL_DEBUG`** (see `docker-compose.yml` + `.env`).

**Why gated:** Response can contain operational data; keep off in production unless debugging.

---

## Key files

| Area | File |
|------|------|
| Derivation, status helpers, eligibility, upsert | `backend/app/api/inventory_status.py` |
| OC fetch + merge + `oc_debug_inbound_detail_raw` | `backend/app/services/oc_client.py` |
| Model (`putaway_at`, `arrived_at`, `raw_payload`) | `backend/app/models/settings.py` (`OCInboundOrder`) |
| Tests | `backend/tests/test_inbound_stage_estimates.py` |
| Env for debug route | `docker-compose.yml`, `backend/app/core/config.py` |

---

## Related docs

- **`docs/HANDOVER_INBOUND_ARRIVED_INCONSISTENCY.md`** — longer narrative of rounds of investigation (merge, proxy, migrations).
- **`docs/HANDOVER_INBOUND_OC_DETAIL_FINDINGS_OPUS.md`** — verbatim OC capture + discussion with vendor / product.

---

## If you change this later

1. **Do not** use **`putaway_at` DB alone** as **Arrived** without the status + eligibility rules above (that recreated “everyone arrived today”).
2. **Do not** assume **merge** fixes missing portal dates if **`debug/inbound-detail-raw`** shows OC never sent those keys.
3. **Keep** eligibility and **status routing** in sync between **upsert** (writing estimates) and **`_extract_inbound_ui_times`** (display), or UI and DB will diverge.
4. After logic changes, run **`pytest tests/test_inbound_stage_estimates.py`**.
