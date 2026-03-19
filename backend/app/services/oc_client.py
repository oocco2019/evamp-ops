"""
OrangeConnex (OC) API client for read-only inventory status integration.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode, urljoin, urlparse
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import encryption_service
from app.models.settings import APICredential, OCConnection


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
    region = (conn.region or "UK").strip().upper()

    # Phase 1: StockSnapshot sweep to discover all MFSKUIDs in region.
    snapshot_rows: List[Dict[str, Any]] = []
    page = 1
    page_size = 200
    while True:
        body = {
            "data": {
                "pageNumber": page,
                "pageSize": page_size,
                "skuList": [],
                "serviceRegionList": [{"serviceRegion": region}],
            },
            "timestamp": int(datetime.now(timezone.utc).timestamp() * 1000),
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
    for m in mapped:
        match = next((s for s in snapshot_rows if str(s.get("MFSKUID") or s.get("mfskuid") or s.get("mfSkuId") or "").strip() == m["mfskuid"]), None)
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
                "service_region": str(match.get("serviceRegion") or region).strip() or region,
            }
    return mapped


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
