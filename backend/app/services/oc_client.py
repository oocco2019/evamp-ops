"""
OrangeConnex (OC) API client for read-only inventory status integration.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timedelta, timezone, date, time as dt_time_min
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin, urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encryption_service
from app.models.settings import APICredential, OCConnection

logger = logging.getLogger(__name__)


class OCConfigError(Exception):
    pass


class OCAPIError(Exception):
    pass


async def _get_active_connection(db: AsyncSession) -> OCConnection:
    result = await db.execute(
        select(OCConnection).where(OCConnection.is_active == True).limit(1)
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise OCConfigError("No active OC connection configured.")
    return conn


async def _get_credential_value(db: AsyncSession, key_name: str) -> str:
    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == "oc",
            APICredential.key_name == key_name,
            APICredential.is_active == True,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise OCConfigError(f"Missing OC credential: {key_name}")
    return encryption_service.decrypt(row.encrypted_value)


def _ensure_no_trailing_slash(value: str) -> str:
    return (value or "").strip().rstrip("/")


def _canonical_path(full_url: str) -> str:
    p = urlparse(full_url)
    path = p.path or "/"
    return path if path.startswith("/") else f"/{path}"


def _sign_request(path: str, body: str, client_id: str, client_secret: str, mode: str) -> str:
    include_body = (mode or "").strip().lower() == "path_and_body"
    payload = body if include_body else ""
    raw = f"{path}|{payload}|{client_id}|{client_secret}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


async def _refresh_access_token(
    db: AsyncSession, oauth_base_url: str, client_id: str, client_secret: str
) -> str:
    refresh_token = await _get_credential_value(db, "refresh_token")
    url = f"{_ensure_no_trailing_slash(oauth_base_url)}/oauth/token"
    attempts: List[str] = []
    payload: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        # Attempt 1: standards-compliant form body + Basic auth
        data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
        resp = await client.post(url, data=data, auth=(client_id, client_secret))
        attempts.append(f"basic_auth+form:{resp.status_code}")
        if resp.status_code < 400:
            payload = resp.json() if resp.text else {}
        else:
            # Attempt 2: form body, no Basic auth
            resp2 = await client.post(url, data=data)
            attempts.append(f"no_auth+form:{resp2.status_code}")
            if resp2.status_code < 400:
                payload = resp2.json() if resp2.text else {}
            else:
                # Attempt 3: query-string style used in OC Postman examples
                params = {
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                }
                resp3 = await client.post(url, params=params)
                attempts.append(f"no_auth+query:{resp3.status_code}")
                if resp3.status_code < 400:
                    payload = resp3.json() if resp3.text else {}
                else:
                    raise OCAPIError(
                        "OC token refresh failed. "
                        f"Attempts={','.join(attempts)} "
                        f"last_response={resp3.text[:300]}"
                    )
    access_token = (payload.get("access_token") or "").strip()
    if not access_token:
        raise OCAPIError("OC token refresh failed: no access_token in response.")
    return access_token


async def oc_build_authorize_url(
    db: AsyncSession, redirect_uri: str, state: Optional[str] = None
) -> str:
    conn = await _get_active_connection(db)
    client_id = await _get_credential_value(db, "client_id")
    oauth_base = _ensure_no_trailing_slash(conn.oauth_base_url)
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri.strip(),
    }
    if state and state.strip():
        query["state"] = state.strip()
    return f"{oauth_base}/oauth/authorize?{urlencode(query)}"


async def oc_exchange_code_for_tokens(
    db: AsyncSession, code: str, redirect_uri: str
) -> Dict[str, Any]:
    conn = await _get_active_connection(db)
    client_id = await _get_credential_value(db, "client_id")
    client_secret = await _get_credential_value(db, "client_secret")
    url = f"{_ensure_no_trailing_slash(conn.oauth_base_url)}/oauth/token"
    clean_code = code.strip()
    clean_redirect = redirect_uri.strip()
    attempts: List[str] = []
    payload: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=30.0) as client:
        data = {
            "grant_type": "authorization_code",
            "code": clean_code,
            "redirect_uri": clean_redirect,
            "client_id": client_id,
        }
        # Attempt 1: standards-compliant form body + Basic auth
        resp = await client.post(url, data=data, auth=(client_id, client_secret))
        attempts.append(f"basic_auth+form:{resp.status_code}")
        if resp.status_code < 400:
            payload = resp.json() if resp.text else {}
        else:
            # Attempt 2: form body, no Basic auth
            resp2 = await client.post(url, data=data)
            attempts.append(f"no_auth+form:{resp2.status_code}")
            if resp2.status_code < 400:
                payload = resp2.json() if resp2.text else {}
            else:
                # Attempt 3: query-string style used in OC Postman examples
                params = {
                    "grant_type": "authorization_code",
                    "code": clean_code,
                    "redirect_uri": clean_redirect,
                    "client_id": client_id,
                }
                resp3 = await client.post(url, params=params)
                attempts.append(f"no_auth+query:{resp3.status_code}")
                if resp3.status_code < 400:
                    payload = resp3.json() if resp3.text else {}
                else:
                    raise OCAPIError(
                        "OC code exchange failed. "
                        f"Attempts={','.join(attempts)} "
                        f"last_response={resp3.text[:300]}"
                    )
    if not isinstance(payload, dict):
        raise OCAPIError("OC code exchange failed: invalid response payload.")
    return payload


async def _call_oc(
    db: AsyncSession,
    connection: OCConnection,
    method: str,
    endpoint_path: str,
    body_obj: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    client_id = await _get_credential_value(db, "client_id")
    client_secret = await _get_credential_value(db, "client_secret")
    access_token = await _refresh_access_token(db, connection.oauth_base_url, client_id, client_secret)

    api_base = _ensure_no_trailing_slash(connection.api_base_url)
    full_url = urljoin(f"{api_base}/", endpoint_path.lstrip("/"))
    path = _canonical_path(full_url)
    body = ""
    if body_obj is not None:
        import json as _json

        body = _json.dumps(body_obj, separators=(",", ":"), ensure_ascii=False)
    signature = _sign_request(path, body, client_id, client_secret, connection.signature_mode)
    # Keep TimeStamp aligned with body timestamp when provided, otherwise current epoch ms.
    body_ts = body_obj.get("timestamp") if isinstance(body_obj, dict) else None
    timestamp_ms = str(body_ts) if body_ts is not None else str(int(time.time() * 1000))

    headers = {
        "Content-Type": "application/json",
        "Access-Token": f"Bearer {access_token}",
        "TimeStamp": timestamp_ms,
        "clientKey": client_id,
        "vAuthorization": signature,
    }
    async with httpx.AsyncClient(timeout=45.0) as client:
        # IMPORTANT: send the exact serialized body string used for signature.
        # Using json=... may re-serialize with different whitespace/order and break vAuthorization.
        resp = await client.request(
            method.upper(),
            full_url,
            headers=headers,
            content=body if body_obj is not None else None,
        )
    if resp.status_code >= 400:
        raise OCAPIError(f"OC API call failed: HTTP {resp.status_code} {resp.text[:400]}")
    if not resp.text:
        return {}
    try:
        return resp.json()
    except Exception as e:  # noqa: BLE001
        raise OCAPIError(f"OC API invalid JSON response: {e}") from e


def _extract_list(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    def _walk(value: Any) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        if isinstance(value, list):
            dict_items = [x for x in value if isinstance(x, dict)]
            if dict_items:
                out.extend(dict_items)
            for item in value:
                out.extend(_walk(item))
        elif isinstance(value, dict):
            for v in value.values():
                out.extend(_walk(v))
        return out

    data = payload.get("data")
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        # OC responses vary by endpoint/version.
        for key in ("list", "items", "result", "rows", "records", "skuList"):
            val = data.get(key)
            if isinstance(val, list):
                return [x for x in val if isinstance(x, dict)]
    # Last resort: recursively find any list of dict-like rows.
    rows = _walk(payload)
    # Keep rows that look SKU-like to reduce noise.
    filtered = []
    for r in rows:
        keys = {k.lower() for k in r.keys()}
        if (
            "mfskuid" in keys
            or "mfskuid".lower() in keys
            or "sellerskuid" in keys
            or "referenceskuid" in keys
            or "seller_skuid" in keys
        ):
            filtered.append(r)
    return filtered if filtered else rows


def _expand_snapshot_service_regions(regions: List[str]) -> List[str]:
    """
    OC stock snapshot filters by serviceRegion. Some tenants use coarse codes (UK, DE, AU)
    but US inventory is keyed under granular regions (e.g. US-South), not plain "US".
    Inbound list responses show serviceRegion like "US-South"; snapshot with only "US" can return no US rows.
    """
    out: List[str] = []
    seen: set[str] = set()
    for raw in regions:
        r = (raw or "").strip()
        if not r:
            continue
        variants: List[str] = [r]
        if r.upper() == "US":
            variants.extend(
                [
                    "US-South",
                    "US-North",
                    "US-West",
                    "US-East",
                ]
            )
        for v in variants:
            if v not in seen:
                seen.add(v)
                out.append(v)
    return out


async def _fetch_snapshot_rows(
    db: AsyncSession,
    conn: OCConnection,
    regions: List[str],
    page_size: int = 200,
) -> List[Dict[str, Any]]:
    snapshot_rows: List[Dict[str, Any]] = []
    for region in _expand_snapshot_service_regions(regions):
        page = 1
        while True:
            body = {
                "data": {
                    "pageNumber": page,
                    "pageSize": page_size,
                    "skuList": [],
                    "serviceRegionList": [{"serviceRegion": region}],
                },
                "messageId": str(uuid4()),
                "timestamp": int(time.time() * 1000),
            }
            resp = await _call_oc(db, conn, "POST", "/openapi/3pp/inventory/v2/snapshot", body_obj=body)
            data = resp.get("data") if isinstance(resp, dict) else {}
            rows = []
            if isinstance(data, dict):
                rows = data.get("SKUList") or data.get("skuList") or []
            if not isinstance(rows, list):
                rows = []
            rows = [r for r in rows if isinstance(r, dict)]
            snapshot_rows.extend(rows)
            if len(rows) < page_size:
                break
            page += 1
            if page > 500:
                break
    return snapshot_rows


async def oc_test_connection(db: AsyncSession) -> Dict[str, Any]:
    conn = await _get_active_connection(db)
    resp = await _call_oc(
        db,
        conn,
        "GET",
        "/openapi/3pp/base/v1/service",
    )
    return {
        "region": conn.region,
        "environment": conn.environment,
        "code": resp.get("code"),
        "service_count": len(_extract_list(resp)),
        "raw": resp,
    }


async def oc_sync_sku_mappings(db: AsyncSession) -> List[Dict[str, Any]]:
    conn = await _get_active_connection(db)
    base_region = (conn.region or "UK").strip().upper()
    regions = [base_region, "US", "DE", "AU"]
    # preserve order while deduping
    regions = list(dict.fromkeys([r for r in regions if r]))

    # Phase 1: StockSnapshot sweep to discover all MFSKUIDs across configured regions.
    snapshot_rows = await _fetch_snapshot_rows(db, conn, regions=regions)

    mfskus = []
    for r in snapshot_rows:
        mfs = str(r.get("MFSKUID") or r.get("mfskuid") or r.get("mfSkuId") or "").strip()
        if mfs:
            mfskus.append(mfs)
    mfskus = sorted(set(mfskus))
    if not mfskus:
        # no inventory rows in region
        return []

    # Phase 2: resolve MFSKUID -> seller/reference via SKUQuery v3
    items: List[Dict[str, Any]] = []
    chunk_size = 50
    now = datetime.now(timezone.utc)
    start = "2020-01-01+0000"
    end = now.strftime("%Y-%m-%d+0000")
    for i in range(0, len(mfskus), chunk_size):
        chunk = mfskus[i:i + chunk_size]
        body = {
            "data": {
                "mfskulist": [{"mfskuid": x} for x in chunk],
                "startTime": start,
                "endTime": end,
                "page": 1,
                "limit": 200,
            }
        }
        resp = await _call_oc(db, conn, "POST", "/openapi/3pp/sku/v3/query", body_obj=body)
        items.extend(_extract_list(resp))

    # Deduplicate by mfskuid/seller key.
    dedup: Dict[str, Dict[str, Any]] = {}
    mapped: List[Dict[str, Any]] = []
    for row in items:
        seller = str(
            row.get("sellerSKUID")
            or row.get("sellerSkuid")
            or row.get("sellerSkuId")
            or row.get("sellerSkuID")
            or ""
        ).strip()
        reference = str(
            row.get("referenceSKUID")
            or row.get("referenceSkuid")
            or row.get("referenceSkuId")
            or row.get("referenceSkuID")
            or ""
        ).strip()
        mfs = str(
            row.get("MFSKUID")
            or row.get("mfskuid")
            or row.get("mfSkuId")
            or row.get("MFSkuId")
            or row.get("mfSKUID")
            or ""
        ).strip()
        if not seller and reference:
            seller = reference
        if not seller or not mfs:
            continue
        dedup_key = f"{seller.lower()}::{mfs.lower()}"
        dedup[dedup_key] = {
            "sku_code": seller,
            "seller_skuid": seller,
            "reference_skuid": reference or seller,
            "mfskuid": mfs,
            "service_region": str(row.get("serviceRegion") or row.get("service_region") or "").strip() or None,
            "raw_payload": row,
        }
    mapped.extend(dedup.values())
    # Attach snapshot rows so caller can persist inventory quantities.
    def _snapshot_region_matches(pref_u: str, snap_region: str) -> bool:
        s_u = (snap_region or "").strip().upper()
        if not pref_u or not s_u:
            return False
        if pref_u == s_u:
            return True
        # SKU query may return "US" while snapshot rows use "US-South", etc.
        if pref_u == "US" and s_u.startswith("US"):
            return True
        return False

    for m in mapped:
        mfs_key = str(m.get("mfskuid") or "").strip()
        pref = str(m.get("service_region") or "").strip().upper()
        candidates = [
            s
            for s in snapshot_rows
            if str(s.get("MFSKUID") or s.get("mfskuid") or s.get("mfSkuId") or "").strip() == mfs_key
        ]
        match = None
        if pref and candidates:
            match = next(
                (s for s in candidates if _snapshot_region_matches(pref, str(s.get("serviceRegion") or ""))),
                None,
            )
        if match is None and candidates:
            match = candidates[0]
        if match:
            m["inventory"] = {
                "available": int(match.get("available") or 0),
                "in_transit": int(match.get("inTransit") or 0),
                "received": int(match.get("received") or 0),
                "reserved_allocated": int(match.get("reservedAllocated") or 0),
                "reserved_hold": int(match.get("reservedHold") or 0),
                "reserved_vas": int(match.get("reservedVAS") or 0),
                "suspend": int(match.get("suspend") or 0),
                "unfulfillable": int(match.get("unfulfillable") or 0),
                "service_region": str(match.get("serviceRegion") or base_region).strip() or base_region,
            }
    return mapped


async def oc_fetch_inventory_rows(db: AsyncSession) -> List[Dict[str, Any]]:
    conn = await _get_active_connection(db)
    base_region = (conn.region or "UK").strip().upper()
    regions = list(dict.fromkeys([base_region, "US", "DE", "AU"]))
    snapshot_rows = await _fetch_snapshot_rows(db, conn, regions=regions)
    out: List[Dict[str, Any]] = []
    for row in snapshot_rows:
        mfskuid = str(row.get("MFSKUID") or row.get("mfskuid") or row.get("mfSkuId") or "").strip()
        if not mfskuid:
            continue
        out.append(
            {
                "mfskuid": mfskuid,
                "service_region": str(row.get("serviceRegion") or "").strip() or base_region,
                "available": int(row.get("available") or 0),
                "in_transit": int(row.get("inTransit") or 0),
                "received": int(row.get("received") or 0),
                "reserved_allocated": int(row.get("reservedAllocated") or 0),
                "reserved_hold": int(row.get("reservedHold") or 0),
                "reserved_vas": int(row.get("reservedVAS") or 0),
                "suspend": int(row.get("suspend") or 0),
                "unfulfillable": int(row.get("unfulfillable") or 0),
            }
        )
    # Dedup by mfskuid+region keeping last seen
    dedup: Dict[str, Dict[str, Any]] = {}
    for x in out:
        dedup[f"{x['mfskuid'].lower()}::{x['service_region'].upper()}"] = x
    return list(dedup.values())


async def oc_fetch_inbound_orders(
    db: AsyncSession,
    service_region: str = "UK",
    page: int = 1,
    page_size: int = 200,
    months_back: int = 6,
    date_from: Optional[date] = None,
    date_to: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """
    Read-only inbound order list from OC.
    Uses OC inbound List Query which is time-range based (ISO+offset with +0000).

    If ``date_from`` is set, the window is [date_from 00:00 UTC, date_to or now] (inclusive end-of-day).
    Otherwise uses rolling ``months_back`` (30-day months) from today.
    OC rejects ranges longer than 7 days; we chunk in 7-day slices (many API calls for long ranges).
    """
    conn = await _get_active_connection(db)
    _ = conn  # explicit; connection is used for signing/auth in _call_oc

    now = datetime.utcnow()
    if date_from is not None:
        start_dt = datetime.combine(date_from, dt_time_min.min)
        if date_to is not None:
            end_dt = date_to
        else:
            end_dt = now.replace(hour=23, minute=59, second=59, microsecond=0)
    else:
        months = max(int(months_back or 6), 0)
        # OC docs show format like "2025-01-01T00:00:00+0000". We use UTC.
        start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=months * 30)
        end_dt = now.replace(hour=23, minute=59, second=59, microsecond=0)

    if start_dt > end_dt:
        return []

    # OC rejects time slots longer than 7 days. We must chunk the query window.
    chunk_days = 7

    # Tenant inbound list endpoint (your tenant returns 404 for other inbound paths).
    endpoint = "/openapi/3pp/inbound/v1/query"

    def _extract_inbound_rows(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(resp, dict):
            return []
        data = resp.get("data")
        if isinstance(data, list):
            return [x for x in data if isinstance(x, dict)]
        if isinstance(data, dict):
            # If it's already a single order object.
            if any(k in data for k in ("inboundOrderNumber", "referenceNumber", "warehouseCode", "status")):
                return [data]
            for key in (
                "inboundOrderList",
                "inboundOrders",
                "inboundOrderResult",
                "inboundList",
                "orderList",
                "orders",
                "rows",
                "records",
                "list",
                "items",
            ):
                val = data.get(key)
                if isinstance(val, list):
                    return [x for x in val if isinstance(x, dict)]
        return []

    def _infer_region_from_warehouse(warehouse_code: str | None) -> str | None:
        if not warehouse_code:
            return None
        # Expected pattern: "UK-xxx", "DE-xxx", "AU-xxx", "US-xxx"
        normalized = (warehouse_code or "").strip().upper()
        if not normalized:
            return None
        if "-" in normalized:
            return normalized.split("-", 1)[0].strip().upper()
        if normalized in {"UK", "DE", "AU", "US"}:
            return normalized
        return None

    def _get_ci(d: Dict[str, Any], *names: str) -> Any:
        """
        Case-insensitive getter for OC responses.
        OC sometimes uses mixed casing like SKUQuantity vs putawayQuantity.
        """
        if not isinstance(d, dict):
            return None
        lower_map = {str(k).lower(): v for k, v in d.items()}
        for n in names:
            key = (n or "").lower()
            if key and key in lower_map:
                return lower_map[key]
        return None

    def _dt_to_oc_time(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S+0000")

    dedup: Dict[str, Dict[str, Any]] = {}
    results: List[Dict[str, Any]] = []

    chunk_start = start_dt
    chunk_index = 0
    logger.info(
        "OC inbound fetch window: %s → %s (UTC), ~%d day(s)",
        _dt_to_oc_time(start_dt),
        _dt_to_oc_time(end_dt),
        max(0, (end_dt - start_dt).days + 1),
    )
    while chunk_start <= end_dt:
        chunk_index += 1
        chunk_end = min(chunk_start + timedelta(days=chunk_days) - timedelta(seconds=1), end_dt)
        start_time = _dt_to_oc_time(chunk_start)
        end_time = _dt_to_oc_time(chunk_end)

        timestamp_ms = int(time.time() * 1000)
        message_id = str(uuid4())

        # Pagination keys vary by tenant/version, so we try a few variants for the same chunk.
        data_variants: List[Dict[str, Any]] = [
            {"startTime": start_time, "endTime": end_time},
            {"startTime": start_time, "endTime": end_time, "page": page, "limit": page_size},
            {"startTime": start_time, "endTime": end_time, "pageNumber": page, "pageSize": page_size},
        ]

        chunk_rows: List[Dict[str, Any]] = []
        for data_variant in data_variants:
            body_obj = {"messageId": message_id, "timestamp": timestamp_ms, "data": data_variant}
            resp = await _call_oc(db, conn, "POST", endpoint, body_obj=body_obj)
            rows = _extract_inbound_rows(resp)
            if not rows:
                continue

            out: List[Dict[str, Any]] = []
            for r in rows:
                if not isinstance(r, dict):
                    continue
                warehouse_code = (
                    _get_ci(r, "warehouseCode", "warehouse_code")
                    or _get_ci(r, "serviceRegion", "service_region")
                    or _get_ci(r, "region")
                    or None
                )
                out.append(
                    {
                        "seller_inbound_number": str(
                            _get_ci(
                                r,
                                "referenceNumber",
                                "sellerInboundNumber",
                                "sellerInboundNo",
                                "sellerinboundNumber",
                                "sellerinboundNo",
                            )
                            or ""
                        ).strip(),
                        "oc_inbound_number": str(
                            _get_ci(r, "inboundOrderNumber", "inboundNumber", "inboundNo") or ""
                        ).strip()
                        or None,
                        "status": str(_get_ci(r, "status", "inboundStatus") or "").strip() or None,
                        "warehouse_code": str(warehouse_code).strip() if warehouse_code is not None else None,
                        "region": _infer_region_from_warehouse(str(warehouse_code)) or None,
                        "shipping_method": str(
                            _get_ci(r, "shippingMethod", "shipping_method")
                            or ""
                        ).strip()
                        or None,
                        "sku_qty": int(_get_ci(r, "skuQty", "sku_qty", "SKUQuantity") or 0),
                        "put_away_qty": int(_get_ci(r, "putAwayQty", "put_away_qty", "putawayQuantity") or 0),
                        "raw_payload": r,
                    }
                )

            chunk_rows = out
            break

        before_chunk = len(results)
        for row in chunk_rows:
            k = f"{(row.get('oc_inbound_number') or '').strip().lower()}::{(row.get('seller_inbound_number') or '').strip().lower()}"
            if k and k in dedup:
                continue
            dedup[k] = row
            results.append(row)
        added = len(results) - before_chunk
        logger.info(
            "OC inbound chunk %d: %s → %s, rows_in_chunk=%d, new_unique=%d, total_unique=%d",
            chunk_index,
            start_time,
            end_time,
            len(chunk_rows),
            added,
            len(results),
        )

        # Advance to the next chunk.
        chunk_start = chunk_end + timedelta(seconds=1)

    logger.info("OC inbound fetch done: total_unique_orders=%d", len(results))
    return results


async def oc_debug_inbound_orders_calls(
    db: AsyncSession, service_region: str = "UK", page: int = 1, page_size: int = 200, months_back: int = 6
) -> Dict[str, Any]:
    """
    Debug helper: tries multiple inbound query endpoints/bodies and returns verbatim OC responses.
    Intended for schema alignment when inbound parsing returns empty rows.
    """
    conn = await _get_active_connection(db)
    _ = conn
    now = datetime.utcnow()
    months = max(int(months_back or 6), 0)
    start_dt = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=months * 30)
    end_dt = now.replace(hour=23, minute=59, second=59, microsecond=0)

    # OC rejects time slots longer than 7 days.
    # For debug, we chunk and show the first few calls.
    chunk_days = 7
    max_chunks_debug = 6

    def _dt_to_oc_time(dt: datetime) -> str:
        return dt.strftime("%Y-%m-%dT%H:%M:%S+0000")

    endpoint = "/openapi/3pp/inbound/v1/query"

    def _extract_inbound_rows(resp: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not isinstance(resp, dict):
            return []
        data = resp.get("data")
        if isinstance(data, dict):
            for key in (
                "inboundOrderList",
                "inboundOrders",
                "inboundOrderResult",
                "inboundList",
                "orderList",
                "orders",
                "rows",
                "records",
            ):
                val = data.get(key)
                if isinstance(val, list) and val:
                    dict_items = [x for x in val if isinstance(x, dict)]
                    if dict_items:
                        return dict_items
        return _extract_list(resp)

    attempts: List[Dict[str, Any]] = []
    last_resp: Dict[str, Any] | None = None

    chunk_start = start_dt
    chunk_idx = 0
    while chunk_start <= end_dt and chunk_idx < max_chunks_debug:
        chunk_end = min(chunk_start + timedelta(days=chunk_days) - timedelta(seconds=1), end_dt)
        start_time = _dt_to_oc_time(chunk_start)
        end_time = _dt_to_oc_time(chunk_end)
        timestamp_ms = int(time.time() * 1000)
        message_id = str(uuid4())

        # For debug we keep it minimal: first page only.
        data_variants: List[Dict[str, Any]] = [
            {"startTime": start_time, "endTime": end_time},
            {"startTime": start_time, "endTime": end_time, "page": page, "limit": page_size},
            {"startTime": start_time, "endTime": end_time, "pageNumber": page, "pageSize": page_size},
        ]

        for data_variant in data_variants:
            body_obj = {"data": data_variant, "messageId": message_id, "timestamp": timestamp_ms}
            try:
                resp = await _call_oc(db, conn, "POST", endpoint, body_obj=body_obj)
                last_resp = resp
                extracted = _extract_inbound_rows(resp)
                attempts.append(
                    {
                        "chunk_start": start_time,
                        "chunk_end": end_time,
                        "endpoint": endpoint,
                        "request_body": body_obj,
                        "oc_response": resp,
                        "extracted_rows": len(extracted),
                    }
                )
            except Exception as e:  # noqa: BLE001
                attempts.append(
                    {
                        "chunk_start": start_time,
                        "chunk_end": end_time,
                        "endpoint": endpoint,
                        "request_body": body_obj,
                        "error": str(e),
                    }
                )

        chunk_start = chunk_end + timedelta(seconds=1)
        chunk_idx += 1

    return {
        "connection": {
            "region": conn.region,
            "environment": conn.environment,
            "oauth_base_url": conn.oauth_base_url,
            "api_base_url": conn.api_base_url,
            "signature_mode": conn.signature_mode,
        },
        "service_region": service_region,
        "page": page,
        "page_size": page_size,
        "attempts": attempts,
        "last_response": last_resp,
    }


async def oc_debug_raw_calls(
    db: AsyncSession, service_region: str = "UK", mfskuid: str = "OC0000029222351"
) -> Dict[str, Any]:
    """
    Raw OC responses for debugging schema/filters.
    Returns verbatim JSON bodies from StockSnapshot v2 and SKUQuery v3.
    """
    conn = await _get_active_connection(db)
    region = (service_region or conn.region or "UK").strip().upper()
    now_ms = int(time.time() * 1000)

    snapshot_body = {
        "data": {
            "pageNumber": 1,
            "pageSize": 5,
            "skuList": [],
            "serviceRegionList": [{"serviceRegion": region}],
        },
        "messageId": str(uuid4()),
        "timestamp": now_ms,
    }
    snapshot_raw = await _call_oc(
        db, conn, "POST", "/openapi/3pp/inventory/v2/snapshot", body_obj=snapshot_body
    )

    sku_body = {
        "data": {
            "mfskulist": [{"mfskuid": (mfskuid or "").strip()}],
            "startTime": "2020-01-01+0000",
            "endTime": "2026-12-31+0000",
            "page": 1,
            "limit": 10,
        },
        "messageId": str(uuid4()),
        "timestamp": now_ms,
    }
    sku_raw = await _call_oc(
        db, conn, "POST", "/openapi/3pp/sku/v3/query", body_obj=sku_body
    )
    return {
        "connection": {
            "region": conn.region,
            "environment": conn.environment,
            "oauth_base_url": conn.oauth_base_url,
            "api_base_url": conn.api_base_url,
            "signature_mode": conn.signature_mode,
        },
        "snapshot_request": snapshot_body,
        "snapshot_response": snapshot_raw,
        "sku_query_request": sku_body,
        "sku_query_response": sku_raw,
    }
