# OrangeConnex GetStockMovement — handoff for Opus / next engineer

## Symptom

User sees **HTTP 502** from our API with detail:

```text
GetStockMovement: Query timeslot is only valid for the last 12 months.
```

That string comes from **OrangeConnex** (OC) JSON (`success: false` / `message` / `errors`), not from nginx. Our backend maps `OCAPIError` from the movement sync path to **502** in `inventory_status.py` (`execute_stock_movement_pull`).

### Context for Opus / ChatGPT / any model without your repo

- **Yes — enough to reason about design and errors:** This file includes architecture, symptom → code path, and **Appendix A (full movement-path source)** so a model can discuss causes, OC behavior, and what to change **without** opening your machine.
- **No — it cannot “see” your project or DB by itself:** There is no live connection to your **database**, **git repo**, or **OrangeConnex tenant**. Line numbers in citations match **this repo** at doc time; if code drifted, verify against current files.
- **Self-contained:** **Appendix A** at the end of this file has **full source** for the movement path—paste **this document alone** for Opus / ChatGPT; no repo or DB access required. For runtime issues, add **one backend log line** with the failing `startTime`/`endTime` and OC response body (redact secrets).
- **DB is not required** for fixing OC request shape / segmentation logic; only **sample rows** or counts matter if the bug is “data not showing” vs “OC returns an error.”

---

## Related code (index)

Full, untruncated Python is in **Appendix A** (end of this doc).

| Area | Files / symbols |
|------|-------------------|
| OC movement fetch | `oc_client.py`: `_MOVEMENT_ENDPOINT` … `oc_fetch_stock_movement_rows` (includes `clamp_oc_movement_query_bounds`, `flatten_stock_movement_response`, `_iter_movement_windows`) |
| HTTP + OAuth | Same file: `_call_oc`, `_get_valid_access_token` (not duplicated in appendix—search in repo) |
| API | `inventory_status.py`: `list_stock_movement`, `execute_stock_movement_pull`, `sync_stock_movement` |
| DB write | `oc_stock_movement_store.py` (full file in appendix) |
| Scheduler | `inventory_refresh_scheduler.py`: `run_scheduled_inventory_refresh` on `INVENTORY_REFRESH_INTERVAL_MINUTES` → includes `execute_stock_movement_pull(..., incremental=True)` |
| UI | `frontend/src/pages/InventoryMovement.tsx`, `frontend/src/services/api.ts` |
| Tests | `backend/tests/test_oc_stock_movement_flatten.py` |

---

## What this integration does

- **Endpoint (OC):** `POST .../openapi/3pp/inventory/v1/movement` (GetStockMovement).
- **Our usage:** `backend/app/services/oc_client.py` — `oc_fetch_stock_movement_rows`, `_MOVEMENT_ENDPOINT`, `_MAX_MOVEMENT_SPAN` (~7 days per **HTTP** call), `_MOVEMENT_SKU_CHUNK` (50 MFSKUIDs per request body).
- **Persistence:** Lines go to PostgreSQL `oc_stock_movement_line`; duplicate `(connection_id, movement_id)` skipped (`oc_stock_movement_store.py`).
- **API surface:** `POST /api/inventory-status/sync-stock-movement` (pull from OC → DB), `GET /api/inventory-status/stock-movement` (read DB for charts).
- **Frontend:** `frontend/src/pages/InventoryMovement.tsx` — **Sync range from OC** / **Incremental sync** (the dedicated “pull all movement” button was removed per product decision).

### Background scheduler (automatic DB fill)

While the FastAPI process is running, `backend/app/services/inventory_refresh_scheduler.py` registers **one** interval job: every **`INVENTORY_REFRESH_INTERVAL_MINUTES`** (default **15**; **`0`** disables the scheduler). Each tick runs, in order: incremental eBay import → OC SKU mappings + inventory snapshot → **`execute_stock_movement_pull(..., incremental=True)`** → incremental inbound cache. That matches **Inventory status → Pull latest data** (manual button). OC movement is therefore refreshed on the **same cadence** as the rest of inventory data, not on a separate daily cron.

---

## How we chunk time (current design)

Per OC (Apifox): GetStockMovement serves **only the past ~12 months** (rolling wall clock) and each query span is **≤ 7 days**.

1. **`clamp_oc_movement_query_bounds`** (`oc_client.py`)  
   Normalizes to UTC, then **`start = max(start, now − 365d)`** and **`end = min(end, now)`**. This is not “segment width”: OC rejects any request whose `startTime` is older than that window.

2. **`_iter_movement_windows`**  
   Splits the clamped `[start, end]` into **≤ ~7 day** windows (one or more POSTs).

3. **SKU batching**  
   Up to **50** `mfSkuId` per POST.

4. **Long-term history**  
   **PostgreSQL** keeps whatever was synced; the app does not TTL-delete movement rows. Keep **`INVENTORY_REFRESH_INTERVAL_MINUTES` > 0** (or use **Pull latest** / **Incremental sync** on Stock & movement) so new lines are stored **before** they age out of OC’s API.

---

## OAuth / HTTP client (relevant for long runs)

- **`_get_valid_access_token`** caches the OC **access token** and refreshes via refresh token; avoids calling `/oauth/token` on **every** inventory HTTP call.
- **Refresh token rotation:** if OC returns a new `refresh_token`, we persist it (`_persist_oc_refresh_token_if_rotated`).
- **`_call_oc`** retries once on 401 / OC JSON that looks like invalid access token.

Files: `backend/app/services/oc_client.py`.

---

## What we already ruled out

- **Multi-year “segment” backfill through OC:** Splitting a 2020–2024 range into 365-day **segments** did not help — every POST still sent a concrete `startTime`/`endTime`, and OC enforces a **rolling 12-month** access window on that absolute time range, not a max chunk size.

- **Removed product path:** A dedicated “pull all movement” backfill that assumed OC would return arbitrarily old history; users rely on **Sync range** + **incremental** sync within OC limits.

---

## If 502 still appears after clamping

Uncommon if `startTime` is within the last 12 months and each window ≤ 7 days: check **auth/token**, **OC outage**, or **timezone** edge cases; logs include the failing window.

---

## Key files (index)

Same paths as **Related code (index)** above; **Appendix A** has the full Python excerpts.

| Area | Path |
|------|------|
| OC client, movement fetch, clamp + 7d windows, `_call_oc` | `backend/app/services/oc_client.py` |
| GET/POST routes, `execute_stock_movement_pull`, `list_stock_movement` | `backend/app/api/inventory_status.py` |
| DB insert | `backend/app/services/oc_stock_movement_store.py` |
| Model | `backend/app/models/settings.py` (`OCStockMovementLine`) |
| Scheduled movement (with inventory interval) | `backend/app/services/inventory_refresh_scheduler.py` |
| UI + API client | `frontend/src/pages/InventoryMovement.tsx`, `frontend/src/services/api.ts` |
| Tests | `backend/tests/test_oc_stock_movement_flatten.py` |

---

## User-facing expectation

- **Charts / GET** read **PostgreSQL** only; they do not call OC.
- **Sync range from OC** pulls what OC allows (last ~12 months, clamped); response may set **`clamped: true`**. Stored rows remain in the DB for reporting beyond OC’s window.
- **502** with the OC message means **OC rejected a specific movement request** — check server logs for the logged window and SKU batch size.

---

## If stuck

Write a short summary: goal, what was tried, exact error text, one log line with failing `startTime`/`endTime`, and point to this doc + **Appendix A**. Another model pass often unblocks faster than repeated guesses.

---

## Appendix A: Full source snapshots (movement path)

**Snapshot date:** 2026-04-03. Regenerate by slicing `oc_client.py` 891–1103, `inventory_status.py` 1170–1382, and full `oc_stock_movement_store.py`.

**Not inlined (same modules):** In `oc_client.py`, helpers such as `_get_active_connection`, `_call_oc`, `_oc_dict_get_ci`, and `OCAPIError` are defined elsewhere in the file. In `inventory_status.py`, imports, `router`, `_active_oc_connection_id`, and Pydantic response types live at the top of the file.

### `backend/app/services/oc_client.py` (lines 891–1103)

```python
# OC GetStockMovement: POST /openapi/3pp/inventory/v1/movement — max ~7 days per HTTP call (we chunk; long spans are multiple calls).
_MOVEMENT_ENDPOINT = "/openapi/3pp/inventory/v1/movement"
_MAX_MOVEMENT_SPAN = timedelta(days=7) - timedelta(seconds=1)
_MOVEMENT_SKU_CHUNK = 50
# OC GetStockMovement: Apifox docs — "past year only" (rolling), plus max 7 days per request.
_OC_MOVEMENT_LOOKBACK_DAYS = 365


def _oc_vendor_inventory_ok(resp: Dict[str, Any]) -> bool:
    if resp.get("success") is False:
        return False
    errs = resp.get("errors")
    if isinstance(errs, list) and len(errs) > 0:
        return False
    code = resp.get("code")
    if code is not None and code not in (0, "0"):
        return False
    return True


def _oc_movement_iso_utc(dt: datetime) -> str:
    """Format as yyyy-MM-dd'T'HH:mm:ss+0000 (OC movement API)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S+0000")


def _iter_movement_windows(start_utc: datetime, end_utc: datetime) -> List[tuple[datetime, datetime]]:
    """Split [start, end] into windows each under 7 days (OC limit)."""
    if start_utc.tzinfo is None:
        start_utc = start_utc.replace(tzinfo=timezone.utc)
    else:
        start_utc = start_utc.astimezone(timezone.utc)
    if end_utc.tzinfo is None:
        end_utc = end_utc.replace(tzinfo=timezone.utc)
    else:
        end_utc = end_utc.astimezone(timezone.utc)
    if start_utc > end_utc:
        return []
    out: List[tuple[datetime, datetime]] = []
    cur = start_utc
    while cur <= end_utc:
        nxt = min(cur + _MAX_MOVEMENT_SPAN, end_utc)
        out.append((cur, nxt))
        if nxt >= end_utc:
            break
        cur = nxt + timedelta(seconds=1)
    return out


def flatten_stock_movement_response(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Parse GetStockMovement JSON: data[] with nested serviceRegionList → inventoryList → movementList.
    """
    if not isinstance(resp, dict) or not _oc_vendor_inventory_ok(resp):
        return []
    data = resp.get("data")
    if not isinstance(data, list):
        return []
    out: List[Dict[str, Any]] = []
    for stock in data:
        if not isinstance(stock, dict):
            continue
        mf = str(_oc_dict_get_ci(stock, "MFSKUID", "mfskuid", "mfSkuId") or "").strip()
        seller = str(stock.get("sellerSkuId") or stock.get("seller_skuid") or "").strip()
        regions = stock.get("serviceRegionList") or stock.get("service_region_list") or []
        if not isinstance(regions, list):
            continue
        for reg in regions:
            if not isinstance(reg, dict):
                continue
            svc_reg = str(reg.get("serviceRegion") or "").strip()
            inv_list = _oc_dict_get_ci(reg, "inventoryList", "inventorylist") or []
            if not isinstance(inv_list, list):
                continue
            for inv in inv_list:
                if not isinstance(inv, dict):
                    continue
                inv_status = str(inv.get("inventoryStatus") or "").strip()
                mlist = inv.get("movementList") or inv.get("movementlist") or []
                if not isinstance(mlist, list):
                    continue
                for mov in mlist:
                    if not isinstance(mov, dict):
                        continue
                    mid = str(
                        _oc_dict_get_ci(mov, "movementID", "moventmentID", "movementId", "movement_id") or ""
                    ).strip()
                    qty = mov.get("quantity")
                    try:
                        qty_i = int(qty) if qty is not None else 0
                    except (TypeError, ValueError):
                        qty_i = 0
                    ac = mov.get("actualCount")
                    try:
                        ac_i = int(ac) if ac is not None else None
                    except (TypeError, ValueError):
                        ac_i = None
                    out.append(
                        {
                            "mfskuid": mf,
                            "seller_skuid": seller or None,
                            "service_region": svc_reg,
                            "inventory_status": inv_status,
                            "movement_id": mid,
                            "quantity": qty_i,
                            "actual_count": ac_i,
                            "reason": (str(mov.get("reason") or "").strip() or None),
                            "order_number": (str(mov.get("orderNumber") or "").strip() or None),
                            "update_time": (str(mov.get("updateTime") or "").strip() or None),
                        }
                    )
    return out


def clamp_oc_movement_query_bounds(
    start_utc: datetime,
    end_utc: datetime,
    *,
    reference_time: Optional[datetime] = None,
) -> tuple[datetime, datetime]:
    """
    OC GetStockMovement only returns inventory movement for the last ~12 months (rolling window from OC).
    Clamp start to max(requested start, now - lookback); cap end to now.
    """
    if start_utc.tzinfo is None:
        start_utc = start_utc.replace(tzinfo=timezone.utc)
    else:
        start_utc = start_utc.astimezone(timezone.utc)
    if end_utc.tzinfo is None:
        end_utc = end_utc.replace(tzinfo=timezone.utc)
    else:
        end_utc = end_utc.astimezone(timezone.utc)

    now_utc = reference_time if reference_time is not None else datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)
    else:
        now_utc = now_utc.astimezone(timezone.utc)

    earliest_allowed = now_utc - timedelta(days=_OC_MOVEMENT_LOOKBACK_DAYS)
    start_utc = max(start_utc, earliest_allowed)
    end_utc = min(end_utc, now_utc)
    return start_utc, end_utc


async def oc_fetch_stock_movement_rows(
    db: AsyncSession,
    mf_sku_ids: List[str],
    start_utc: datetime,
    end_utc: datetime,
) -> List[Dict[str, Any]]:
    """
    Call OC GetStockMovement for the given MFSKUIDs and UTC range.
    OC only serves the last ~12 months; range is clamped. Within that span, requests use ≤7-day windows
    and SKU batches of 50.
    """
    conn = await _get_active_connection(db)
    ids = sorted({str(x).strip() for x in mf_sku_ids if str(x).strip()})
    if not ids:
        return []

    start_utc, end_utc = clamp_oc_movement_query_bounds(start_utc, end_utc)
    if start_utc >= end_utc:
        return []

    windows = _iter_movement_windows(start_utc, end_utc)
    all_rows: List[Dict[str, Any]] = []
    for win_start, win_end in windows:
        for i in range(0, len(ids), _MOVEMENT_SKU_CHUNK):
            chunk = ids[i : i + _MOVEMENT_SKU_CHUNK]
            body = {
                "data": {
                    "startTime": _oc_movement_iso_utc(win_start),
                    "endTime": _oc_movement_iso_utc(win_end),
                    "mfSkuList": [{"mfSkuId": x} for x in chunk],
                },
                "messageId": str(uuid4()),
                "timestamp": int(time.time() * 1000),
            }
            resp = await _call_oc(db, conn, "POST", _MOVEMENT_ENDPOINT, body_obj=body)
            if not _oc_vendor_inventory_ok(resp):
                msg = resp.get("message") or "OC movement request failed"
                errs = resp.get("errors")
                if isinstance(errs, list) and errs:
                    first = errs[0] if isinstance(errs[0], dict) else {}
                    msg = str(first.get("message") or msg)
                logger.warning(
                    "GetStockMovement OC error window=%s..%s mf_skus=%d first_msg=%s",
                    win_start.isoformat(),
                    win_end.isoformat(),
                    len(chunk),
                    msg[:500],
                )
                raise OCAPIError(f"GetStockMovement: {msg}")
            all_rows.extend(flatten_stock_movement_response(resp))

    # De-dupe when movement_id is present (chunk overlap should not duplicate).
    seen: set[tuple[str, str, str, str]] = set()
    deduped: List[Dict[str, Any]] = []
    for r in all_rows:
        mid = (r.get("movement_id") or "").strip()
        if mid:
            key = (mid, (r.get("mfskuid") or ""), (r.get("service_region") or ""), (r.get("update_time") or ""))
            if key in seen:
                continue
            seen.add(key)
        deduped.append(r)

    deduped.sort(key=lambda x: (x.get("update_time") or "", x.get("mfskuid") or ""))
    return deduped
```

### `backend/app/api/inventory_status.py` (lines 1170–1382)

```python
    return payload


async def _resolve_mfsku_list_for_movement(
    db: AsyncSession,
    cid: int,
    seller_skuid: Optional[str],
    sku_code: Optional[str],
    mfskuid: Optional[str],
) -> tuple[List[str], str]:
    """Return (mfsku ids, scope filtered|all_mapped_skus)."""
    scope = "filtered"
    mf_key = (mfskuid or "").strip()
    mfs: List[str] = []
    if mf_key:
        mfs = [mf_key]
    elif (seller_skuid or "").strip():
        sk = seller_skuid.strip()
        mr = await db.execute(
            select(OCSkuMapping.mfskuid).where(
                OCSkuMapping.connection_id == cid,
                OCSkuMapping.seller_skuid == sk,
            )
        )
        mfs = [row[0] for row in mr.all() if row[0]]
    elif (sku_code or "").strip():
        sc = sku_code.strip()
        mr = await db.execute(
            select(OCSkuMapping.mfskuid).where(
                OCSkuMapping.connection_id == cid,
                OCSkuMapping.sku_code == sc,
            )
        )
        mfs = [row[0] for row in mr.all() if row[0]]
    else:
        scope = "all_mapped_skus"
        mr = await db.execute(
            select(OCSkuMapping.mfskuid).where(OCSkuMapping.connection_id == cid).distinct()
        )
        mfs = sorted({str(row[0]).strip() for row in mr.all() if row[0]})
    return mfs, scope


@router.get("/stock-movement", response_model=OCStockMovementResponse)
async def list_stock_movement(
    db: AsyncSession = Depends(get_db),
    from_date: Optional[date] = Query(None, alias="from"),
    to_date: Optional[date] = Query(None, alias="to"),
    seller_skuid: Optional[str] = None,
    sku_code: Optional[str] = None,
    mfskuid: Optional[str] = None,
    line_limit: int = Query(25_000, ge=500, le=100_000, description="Max movement lines returned (newest first if truncated)."),
):
    """Movement lines persisted from OC GetStockMovement (POST /sync-stock-movement)."""
    cid = await _active_oc_connection_id(db)
    if not cid:
        raise HTTPException(status_code=400, detail="No active OC connection configured.")

    mfs, scope = await _resolve_mfsku_list_for_movement(db, cid, seller_skuid, sku_code, mfskuid)
    if not mfs:
        return OCStockMovementResponse(
            rows=[],
            from_date=(from_date or date.today()).isoformat(),
            to_date=(to_date or date.today()).isoformat(),
            row_count=0,
            scope=scope,
            mfskuid_count=0,
        )

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    eff_to = to_date or now_naive.date()
    eff_from = from_date or (eff_to - timedelta(days=30))
    start_dt = datetime.combine(eff_from, dt_time.min)
    end_dt = datetime.combine(eff_to, dt_time.max)

    mf_list = list({str(x).strip().lower() for x in mfs if str(x).strip()})
    stmt = select(OCStockMovementLine).where(
        OCStockMovementLine.connection_id == cid,
        func.lower(OCStockMovementLine.mfskuid).in_(mf_list),
        OCStockMovementLine.update_time_utc.isnot(None),
        OCStockMovementLine.update_time_utc >= start_dt,
        OCStockMovementLine.update_time_utc <= end_dt,
    )
    stmt = stmt.order_by(OCStockMovementLine.update_time_utc.asc(), OCStockMovementLine.id.asc())
    res = await db.execute(stmt)
    db_rows = list(res.scalars().all())

    truncated = False
    if len(db_rows) > line_limit:
        db_rows = db_rows[-line_limit:]
        truncated = True

    map_result = await db.execute(select(OCSkuMapping).where(OCSkuMapping.connection_id == cid))
    mappings = list(map_result.scalars().all())
    sku_by_mf_lower: dict[str, str] = {}
    for m in mappings:
        k = (m.mfskuid or "").strip().lower()
        if k and k not in sku_by_mf_lower:
            sku_by_mf_lower[k] = (m.sku_code or "").strip()

    out_rows: List[OCStockMovementRowResponse] = []
    for row in db_rows:
        mfk = (row.mfskuid or "").strip().lower()
        sku_c = sku_by_mf_lower.get(mfk) or None
        out_rows.append(
            OCStockMovementRowResponse(
                update_time=row.update_time_raw or "",
                mfskuid=str(row.mfskuid or ""),
                sku_code=sku_c or None,
                seller_skuid=row.seller_skuid,
                service_region=str(row.service_region or ""),
                inventory_status=str(row.inventory_status or ""),
                movement_id=str(row.movement_id or ""),
                quantity=int(row.quantity or 0),
                actual_count=row.actual_count,
                reason=row.reason,
                order_number=row.order_number,
            )
        )

    return OCStockMovementResponse(
        rows=out_rows,
        from_date=eff_from.isoformat(),
        to_date=eff_to.isoformat(),
        row_count=len(out_rows),
        scope=scope,
        mfskuid_count=len(mfs),
        truncated=truncated,
        line_limit=line_limit if truncated else None,
    )


async def execute_stock_movement_pull(
    db: AsyncSession,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    incremental: bool = False,
) -> SyncStockMovementResponse:
    """
    Pull GetStockMovement from OrangeConnex for the date range and upsert into oc_stock_movement_line.
    OC only exposes ~the last 12 months; older intervals are clamped (see clamped on response).
    Rows we insert are kept indefinitely in PostgreSQL — run incremental sync regularly so history is
    captured before it ages out of OC's API window.
    If incremental=True and from_date is omitted, starts ~2 days before the newest stored movement (or last 14d if empty).
    """
    cid = await _active_oc_connection_id(db)
    if not cid:
        raise HTTPException(status_code=400, detail="No active OC connection configured.")

    now_naive = datetime.now(timezone.utc).replace(tzinfo=None)
    eff_to = to_date or now_naive.date()

    mfs, scope = await _resolve_mfsku_list_for_movement(db, cid, None, None, None)
    if not mfs:
        return SyncStockMovementResponse(
            fetched=0,
            inserted=0,
            from_date=eff_to.isoformat(),
            to_date=eff_to.isoformat(),
            mfskuid_count=0,
            scope="all_mapped_skus",
            clamped=False,
        )

    if from_date:
        eff_from = from_date
    elif incremental:
        wm = await max_movement_update_time_utc(db, cid)
        if wm:
            if wm.tzinfo is not None:
                wm = wm.astimezone(timezone.utc).replace(tzinfo=None)
            wm_date = wm.date() if isinstance(wm, datetime) else eff_to
            eff_from = max(wm_date - timedelta(days=2), eff_to - timedelta(days=365))
        else:
            eff_from = eff_to - timedelta(days=14)
    else:
        eff_from = eff_to - timedelta(days=30)

    start_utc = datetime.combine(eff_from, dt_time.min, tzinfo=timezone.utc)
    end_utc = datetime.combine(eff_to, dt_time.max, tzinfo=timezone.utc)

    c_start, c_end = clamp_oc_movement_query_bounds(start_utc, end_utc)
    clamped = (c_start != start_utc) or (c_end != end_utc)
    if clamped:
        logger.info(
            "Stock movement range clamped for OC GetStockMovement (12-month API limit): requested %s..%s -> %s..%s",
            start_utc.isoformat(),
            end_utc.isoformat(),
            c_start.isoformat(),
            c_end.isoformat(),
        )

    if c_start >= c_end:
        return SyncStockMovementResponse(
            fetched=0,
            inserted=0,
            from_date=c_start.date().isoformat(),
            to_date=c_end.date().isoformat(),
            mfskuid_count=len(mfs),
            scope=scope,
            clamped=clamped,
        )

    try:
        raw_rows = await oc_fetch_stock_movement_rows(db, mfs, start_utc, end_utc)
    except OCAPIError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e

    inserted = await persist_oc_stock_movement_lines(db, cid, raw_rows)
    await db.commit()
    return SyncStockMovementResponse(
        fetched=len(raw_rows),
        inserted=inserted,
```

### `backend/app/services/oc_stock_movement_store.py` (full file)

```python
"""Persist OC GetStockMovement lines to PostgreSQL (idempotent upserts; rows are not TTL-pruned by this app)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import OCStockMovementLine


_OC_TIME_RE = re.compile(r"^(.+)([+-])(\d{2})(\d{2})$")


def parse_oc_update_time_to_utc_naive(s: Optional[str]) -> Optional[datetime]:
    """Parse OC time strings like 2024-07-15T19:48:37+0800 to naive UTC."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    m = _OC_TIME_RE.match(s)
    if m:
        base, sign, zh, zm = m.groups()
        s = f"{base}{sign}{zh}:{zm}"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


async def persist_oc_stock_movement_lines(
    db: AsyncSession,
    connection_id: int,
    rows: List[Dict[str, Any]],
) -> int:
    """Insert movement rows; skip duplicates on (connection_id, movement_id). Returns newly inserted count."""
    if not rows:
        return 0
    payloads: List[Dict[str, Any]] = []
    for r in rows:
        mid = str(r.get("movement_id") or "").strip()
        if not mid:
            continue
        ut_raw = str(r.get("update_time") or "").strip()
        payloads.append(
            {
                "connection_id": connection_id,
                "mfskuid": str(r.get("mfskuid") or "").strip() or "",
                "seller_skuid": r.get("seller_skuid"),
                "service_region": str(r.get("service_region") or "").strip(),
                "inventory_status": str(r.get("inventory_status") or "").strip(),
                "movement_id": mid,
                "quantity": int(r.get("quantity") or 0),
                "actual_count": r.get("actual_count"),
                "reason": r.get("reason"),
                "order_number": r.get("order_number"),
                "update_time_raw": ut_raw,
                "update_time_utc": parse_oc_update_time_to_utc_naive(ut_raw),
            }
        )
    if not payloads:
        return 0
    inserted = 0
    batch = 400
    for i in range(0, len(payloads), batch):
        chunk = payloads[i : i + batch]
        stmt = pg_insert(OCStockMovementLine).values(chunk)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_oc_stock_mov_conn_movement")
        res = await db.execute(stmt)
        rc = res.rowcount
        if rc is not None:
            inserted += int(rc)
    return inserted


async def max_movement_update_time_utc(db: AsyncSession, connection_id: int) -> Optional[datetime]:
    r = await db.execute(
        select(func.max(OCStockMovementLine.update_time_utc)).where(
            OCStockMovementLine.connection_id == connection_id
        )
    )
    return r.scalar_one_or_none()
```
