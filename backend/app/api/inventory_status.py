"""
Inventory status API (OrangeConnex, read-only).
"""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone, time as dt_time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, func, case, or_
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.models.settings import APICredential, OCConnection, OCSkuMapping, OCSkuInventory, OCInboundOrder
from app.models.messages import SyncMetadata
from app.models.stock import LineItem, Order
from app.core.security import encryption_service
from app.services.oc_client import (
    OCAPIError,
    OCConfigError,
    oc_build_authorize_url,
    oc_debug_inbound_detail_raw,
    oc_debug_raw_calls,
    oc_exchange_code_for_tokens,
    oc_fetch_inbound_orders,
    oc_fetch_inventory_rows,
    oc_sync_sku_mappings,
    oc_test_connection,
)

router = APIRouter()
logger = logging.getLogger(__name__)

SYNC_META_INBOUND_LAST = "oc_inbound_last_sync_at"
SYNC_META_INBOUND_STATUS_FILTER = "inventory_inbound_status_filter_excluded"


def _inbound_status_is_canceled(status: Optional[str]) -> bool:
    """True if OC status indicates the inbound was canceled (Canceled, Cancelled, etc.)."""
    return "cancel" in (status or "").strip().lower()


def _inbound_not_canceled_sql():
    """SQL predicate: exclude rows whose status contains 'cancel' (case-insensitive)."""
    return ~func.lower(func.coalesce(OCInboundOrder.status, "")).like("%cancel%")


class OCConnectionUpsertRequest(BaseModel):
    name: str = "OC"
    region: str = "UK"
    environment: str = Field(default="stage", pattern="^(stage|prod)$")
    oauth_base_url: str
    api_base_url: str
    signature_mode: str = Field(default="path_and_body", pattern="^(path_only|path_and_body)$")
    is_active: bool = True


class OCConnectionResponse(BaseModel):
    id: int
    name: str
    region: str
    environment: str
    oauth_base_url: str
    api_base_url: str
    signature_mode: str
    is_active: bool
    updated_at: datetime

    model_config = {"from_attributes": True}


class InventoryStatusSummary(BaseModel):
    connection: Optional[OCConnectionResponse]
    credentials_present: List[str]
    has_required_credentials: bool
    mapping_count: int
    last_sync_at: Optional[datetime]


class ConnectionTestResponse(BaseModel):
    ok: bool
    detail: str
    region: Optional[str] = None
    environment: Optional[str] = None
    service_count: Optional[int] = None


class SkuMappingResponse(BaseModel):
    id: int
    sku_code: str
    seller_skuid: str
    reference_skuid: str
    mfskuid: str
    service_region: Optional[str]
    last_synced_at: datetime

    model_config = {"from_attributes": True}


class SyncSkuResponse(BaseModel):
    synced: int
    skipped: int
    inventory_rows: int


class OCSkuInventoryResponse(BaseModel):
    id: int
    seller_skuid: Optional[str] = None
    mfskuid: str
    service_region: str
    available: int
    in_transit: int
    received: int
    reserved_allocated: int
    reserved_hold: int
    reserved_vas: int
    suspend: int
    unfulfillable: int
    sold_3m_units: int = 0
    sold_1m_units: int = 0
    synced_at: datetime

    model_config = {"from_attributes": True}


class OCAuthUrlRequest(BaseModel):
    redirect_uri: str
    state: Optional[str] = None


class OCAuthUrlResponse(BaseModel):
    authorize_url: str


class OCExchangeCodeRequest(BaseModel):
    code: str
    redirect_uri: str


class OCExchangeCodeResponse(BaseModel):
    access_token_received: bool
    refresh_token_stored: bool
    expires_in: Optional[int] = None


class OCRawDebugResponse(BaseModel):
    connection: dict
    snapshot_request: dict
    snapshot_response: dict
    sku_query_request: dict
    sku_query_response: dict


class OCInboundRawDebugResponse(BaseModel):
    connection: dict
    service_region: str
    page: int
    page_size: int
    attempts: list[dict]
    last_response: dict | None = None


class InboundOrderLookupResponse(BaseModel):
    """Transparent view of one cached inbound row (DB + parsed OC JSON + computed display times)."""

    request_method: str = "GET"
    request_url: str
    oc_inbound_number: str
    seller_inbound_number: Optional[str] = None
    status: Optional[str] = None
    warehouse_code: Optional[str] = None
    region: Optional[str] = None
    shipping_method: Optional[str] = None
    sku_qty: int = 0
    put_away_qty: int = 0
    inbound_at_db: Optional[str] = Field(None, description="Stored inbound_at from sync (ISO).")
    synced_at_db: Optional[str] = Field(None, description="Last OC sync time for this row (ISO).")
    putaway_at_db: Optional[str] = Field(None, description="Stored putaway_at estimate from sync (ISO).")
    arrived_at_db: Optional[str] = Field(None, description="Stored arrived_at estimate from sync (ISO).")
    create_time: Optional[str] = None
    putaway_time: Optional[str] = None
    arrived_time: Optional[str] = None
    has_raw_payload: bool = False
    raw_oc_payload: Optional[Dict[str, Any]] = Field(
        None,
        description="Full JSON from oc_inbound_orders.raw_payload after last sync (merged list/detail/label).",
    )
    transparency: str = Field(
        default=(
            "create_time / putaway_time / arrived_time come from _extract_inbound_ui_times(). "
            "create_time is EvampOps first-seen sync timestamp (inbound_at_db). "
            "putaway/arrived come from raw_oc_payload parsing (flattened scalars + batchList.arrivalTime). "
            "Arrived does not fall back to first-seen sync time; if OC omits arrival timestamps, Arrived may be blank. "
            "Official Postman samples only document inbound creation; query/detail response shapes vary by tenant."
        )
    )


class OCInboundOrderResponse(BaseModel):
    seller_inbound_number: str
    oc_inbound_number: Optional[str] = None
    status: Optional[str] = None
    warehouse_code: Optional[str] = None
    region: Optional[str] = None
    shipping_method: Optional[str] = None
    sku_qty: int = 0
    put_away_qty: int = 0
    inbound_at: Optional[datetime] = None
    synced_at: Optional[datetime] = None
    create_time: Optional[str] = Field(
        default=None,
        description="EvampOps first-seen sync timestamp (YYYY-MM-DD HH:MM:SS), computed server-side from inbound_at/synced_at.",
    )
    putaway_time: Optional[str] = Field(default=None, description="Display putaway time from OC raw, server-side.")
    arrived_time: Optional[str] = Field(
        default=None,
        description="Display arrived time from OC raw (server-side). Blank if OC omits arrival timestamps.",
    )
    raw: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Full OrangeConnex row JSON from the last sync (only when include_raw=true).",
    )


class InboundOrderStatusSlice(BaseModel):
    status: str
    count: int


class InboundOrderStatusSummaryResponse(BaseModel):
    """Aggregated inbound order counts by status (cached DB; sync via POST /inbound-orders/sync)."""

    from_date: str
    to_date: str
    total_orders: int
    slices: List[InboundOrderStatusSlice]
    last_sync_at: Optional[str] = None


class InboundSyncResponse(BaseModel):
    synced: int
    message: str
    full: bool


class InboundStatusFilterResponse(BaseModel):
    """Which inbound status values are hidden in the UI (Excel-style column filter)."""

    excluded: List[str] = Field(default_factory=list)


class InboundStatusFilterPut(BaseModel):
    excluded: List[str] = Field(default_factory=list)


# Earliest date for historic inbound status chart (inclusive, UTC).
INBOUND_STATUS_CHART_FROM = date(2024, 1, 1)
# Incremental inbound sync overlap window (days) to catch late status transitions.
INBOUND_INCREMENTAL_OVERLAP_DAYS = 14


def _status_indicates_putaway(status_lower: str) -> bool:
    """Heuristic for OC status strings that indicate putaway/processed-at-warehouse."""
    status_lower = (status_lower or "").strip().lower()
    if not status_lower:
        return False
    if "put away" in status_lower or "putaway" in status_lower:
        return True
    # Some tenants use "Partially Put away"
    if "partial" in status_lower and "put" in status_lower and "away" in status_lower:
        return True
    # Lifecycle wording seen on some tenants (portal still shows arrival for these).
    if "inbound complete" in status_lower or "inbound completed" in status_lower:
        return True
    if "goods received" in status_lower or "warehouse received" in status_lower:
        return True
    if "checked in" in status_lower and ("warehouse" in status_lower or "inbound" in status_lower):
        return True
    return False


def _status_indicates_arrived(status_lower: str) -> bool:
    """Heuristic for OC status strings that indicate arrived-at-destination."""
    status_lower = (status_lower or "").strip().lower()
    if not status_lower:
        return False
    if "arrived" not in status_lower:
        return False
    # Avoid treating "not arrived" as arrived.
    if "not arrived" in status_lower:
        return False
    return True


def _status_indicates_other_warehouse(status_lower: str) -> bool:
    """
    Warehouse / processing-ish status that is neither arrived nor putaway heuristics.
    Synthetic arrival (EvampOps first-seen estimate) applies only when OC omits times.
    """
    status_lower = (status_lower or "").strip().lower()
    if not status_lower:
        return False
    if _status_indicates_arrived(status_lower) or _status_indicates_putaway(status_lower):
        return False
    if "cancel" in status_lower:
        return False
    if "transit" in status_lower or "not arrived" in status_lower:
        return False
    return any(
        k in status_lower
        for k in (
            "processing",
            "receiving",
            "sorting",
            "warehouse",
            "inspection",
            "quality",
            "hold",
            "qc",
        )
    )


def _putaway_qty_transitioned(prev_put_away_qty: int, new_put_away_qty: int) -> bool:
    """True when putaway quantity first becomes > 0."""
    return prev_put_away_qty <= 0 and new_put_away_qty > 0


def _should_set_putaway_at(
    existing_putaway_at: Optional[datetime],
    prev_put_away_qty: int,
    new_put_away_qty: int,
    prev_status_lower: str,
    status_lower: str,
) -> bool:
    if existing_putaway_at is not None:
        return False
    if _putaway_qty_transitioned(prev_put_away_qty, new_put_away_qty):
        return True
    return (not _status_indicates_putaway(prev_status_lower)) and _status_indicates_putaway(status_lower)


def _should_set_arrived_at(
    existing_arrived_at: Optional[datetime],
    prev_put_away_qty: int,
    new_put_away_qty: int,
    prev_status_lower: str,
    status_lower: str,
) -> bool:
    if existing_arrived_at is not None:
        return False
    if _putaway_qty_transitioned(prev_put_away_qty, new_put_away_qty):
        # If OC doesn't provide an explicit arrived timestamp, treat the moment we first see
        # putaway quantity > 0 as a rough warehouse-received proxy.
        return True
    return (not _status_indicates_arrived(prev_status_lower)) and _status_indicates_arrived(status_lower)


def _eligible_for_inbound_stage_estimates(now_utc_naive: datetime, first_seen: Optional[datetime]) -> bool:
    """
    Apply putaway_at / arrived_at sync-time estimates (and DB-backed UI fallbacks) only for
    orders first seen on or after the start of **yesterday** (UTC). Older rows rely on OC raw
    timestamps only.
    """
    if first_seen is None:
        return False
    cutoff = datetime.combine(now_utc_naive.date() - timedelta(days=1), dt_time.min)
    return first_seen >= cutoff


async def _active_oc_connection_id(db: AsyncSession) -> Optional[int]:
    r = await db.execute(select(OCConnection.id).where(OCConnection.is_active == True).limit(1))
    row = r.first()
    return int(row[0]) if row else None


def _inbound_dedup_key(seller: str, oc: Optional[str]) -> str:
    s = (seller or "").strip().lower()
    o = (oc or "").strip().lower()
    return f"{o}::{s}"


def _flatten_oc_scalar_fields(d: Any, depth: int = 0) -> List[tuple[str, Any]]:
    """Collect (key_lower, scalar_value) from nested OC JSON; dict/list values are recursed."""
    if depth > 12 or not isinstance(d, dict):
        return []
    out: List[tuple[str, Any]] = []
    for k, v in d.items():
        kl = str(k).lower()
        if isinstance(v, dict):
            out.extend(_flatten_oc_scalar_fields(v, depth + 1))
        elif isinstance(v, list):
            for item in v:
                if isinstance(item, dict):
                    out.extend(_flatten_oc_scalar_fields(item, depth + 1))
        else:
            out.append((kl, v))
    return out


def _parse_oc_scalar_to_utc_naive(v: Any) -> Optional[datetime]:
    """Parse OC timestamp: epoch ms, epoch s, ISO, or 'YYYY-MM-DD HH:MM:SS'."""
    if v is None or isinstance(v, bool) or v == "":
        return None
    if isinstance(v, (int, float)):
        n = float(v)
        if n > 1e12:
            return datetime.utcfromtimestamp(n / 1000.0)
        if n > 1e9:
            return datetime.utcfromtimestamp(n)
        return None
    if not isinstance(v, str):
        return None
    s = str(v).strip()
    if not s:
        return None
    # OC sometimes returns epoch timestamps as numeric strings.
    if re.match(r"^-?\d+(\.\d+)?$", s):
        try:
            n = float(s)
            if n > 1e12:
                return datetime.utcfromtimestamp(n / 1000.0)
            if n > 1e9:
                return datetime.utcfromtimestamp(n)
            return None
        except (ValueError, TypeError):
            return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    elif s.endswith("+0000"):
        s = s[:-5] + "+00:00"
    elif re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}", s):
        s = re.sub(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", r"\1T\2", s)
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", s):
        # OC sometimes sends date-only strings; interpret as midnight UTC.
        try:
            return datetime.strptime(s, "%Y-%m-%d")
        except ValueError:
            return None
    try:
        dt = datetime.fromisoformat(s)
        return dt.replace(tzinfo=None) if dt.tzinfo else dt
    except (ValueError, TypeError):
        return None


def _inbound_status_lower_for_ui(
    raw: Optional[Dict[str, Any]],
    flat: List[tuple[str, Any]],
    status_from_row: Optional[str],
) -> str:
    if status_from_row and str(status_from_row).strip():
        return str(status_from_row).strip().lower()
    for kl, v in flat:
        if kl in ("status", "inboundstatus"):
            s = str(v or "").strip().lower()
            if s:
                return s
    if isinstance(raw, dict):
        s = raw.get("status") or raw.get("inboundStatus")
        if s is not None and str(s).strip():
            return str(s).strip().lower()
    return ""


def _extract_inbound_ui_times(
    raw: Optional[Dict[str, Any]],
    inbound_at_db: Optional[datetime],
    putaway_at_db: Optional[datetime] = None,
    arrived_at_db: Optional[datetime] = None,
    *,
    status_from_row: Optional[str] = None,
    now_utc_naive: Optional[datetime] = None,
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Stable display times for the inbound table (YYYY-MM-DD HH:MM:SS, UTC from OC numeric / parsed strings).

    ``inbound_at_db`` is EvampOps first-seen time (``inbound_at`` or ``synced_at``) used for create time
    and for eligibility: first-seen on or after **yesterday UTC** may use DB estimates when OC omits times.

    When eligible: **arrived**-ish status → ``arrived_at`` estimate for Arrived column; **putaway**-ish →
    ``putaway_at`` for Putaway; **other** warehouse processing → synthetic **arrival** only
    (``arrived_at`` or ``putaway_at``).
    """

    def fmt(dt: Optional[datetime]) -> Optional[str]:
        if dt is None:
            return None
        return dt.strftime("%Y-%m-%d %H:%M:%S")

    if not raw:
        return (fmt(inbound_at_db), None, None)

    flat = _flatten_oc_scalar_fields(raw)
    status_val = _inbound_status_lower_for_ui(raw, flat, status_from_row)
    now = now_utc_naive or datetime.utcnow()
    eligible = _eligible_for_inbound_stage_estimates(now, inbound_at_db)

    # Business rule: UI "create time" is the first-seen sync timestamp in EvampOps.
    create_dt: Optional[datetime] = inbound_at_db

    putaway_dt: Optional[datetime] = None
    putaway_from_raw: bool = False
    for kl, v in flat:
        if kl in ("putawaytime", "put_away_time", "completeputawaytime"):
            putaway_dt = _parse_oc_scalar_to_utc_naive(v)
            if putaway_dt:
                putaway_from_raw = True
                break
    if putaway_dt is None:
        for kl, v in flat:
            if "putaway" in kl and "time" in kl and "qty" not in kl and "quantity" not in kl:
                putaway_dt = _parse_oc_scalar_to_utc_naive(v)
                if putaway_dt:
                    putaway_from_raw = True
                    break

    # Persisted putaway estimate: only for putaway-indicating status and first-seen since yesterday (UTC).
    if putaway_dt is None and putaway_at_db is not None and eligible and _status_indicates_putaway(status_val):
        putaway_dt = putaway_at_db

    arrived_dt: Optional[datetime] = None
    arrived_candidates: List[datetime] = []

    for kl, v in flat:
        if kl in ("arrivedtime", "arrivaltime", "actualarrivaltime", "actualarrival"):
            dt = _parse_oc_scalar_to_utc_naive(v)
            if dt:
                arrived_candidates.append(dt)
    if arrived_candidates:
        arrived_dt = min(arrived_candidates)

    if arrived_dt is None:
        for kl, v in flat:
            if ("arrival" in kl or "arrived" in kl) and "estimate" not in kl and "eta" not in kl:
                # Support either "...time..." or "...date..." keys.
                if ("time" in kl) or ("date" in kl):
                    dt = _parse_oc_scalar_to_utc_naive(v)
                    if dt:
                        arrived_candidates.append(dt)
        if arrived_candidates:
            arrived_dt = min(arrived_candidates)

    if arrived_dt is None:
        batch_list = raw.get("batchList") if isinstance(raw.get("batchList"), list) else raw.get("batchlist")
        if isinstance(batch_list, list):
            dt_candidates: List[datetime] = []
            for item in batch_list:
                if not isinstance(item, dict):
                    continue
                at = item.get("arrivalTime") or item.get("arrivaltime")
                dt = _parse_oc_scalar_to_utc_naive(at)
                if dt:
                    dt_candidates.append(dt)
            if dt_candidates:
                arrived_dt = min(dt_candidates)

    # OC real putaway timestamp → arrival proxy for putaway statuses (not DB estimate).
    if arrived_dt is None and putaway_dt is not None and putaway_from_raw:
        if status_val and _status_indicates_putaway(status_val):
            arrived_dt = putaway_dt

    # EvampOps first-seen estimates (sync): only when first-seen since yesterday UTC.
    if arrived_dt is None and eligible:
        if _status_indicates_arrived(status_val) and (arrived_at_db is not None or putaway_at_db is not None):
            arrived_dt = arrived_at_db or putaway_at_db
        elif _status_indicates_other_warehouse(status_val) and (arrived_at_db is not None or putaway_at_db is not None):
            arrived_dt = arrived_at_db or putaway_at_db

    return (fmt(create_dt), fmt(putaway_dt), fmt(arrived_dt))


def _parse_inbound_at(raw: Any) -> Optional[datetime]:
    """
    Best-effort time from OC list or merged detail payload (stored as inbound_at for sorting / fallback).
    Top-level keys only; OC uses createtime, gmtCreate, +0000, Z, epoch ms.
    """
    if not isinstance(raw, dict):
        return None
    lower = {str(k).lower(): v for k, v in raw.items()}
    for k in (
        "createtime",
        "createdtime",
        "inboundcreatetime",
        "createddate",
        "inboundcreatedtime",
        "gmtcreate",
        "gmt_create",
        "ordercreatetime",
        "putawaytime",
        "arrivedtime",
        "arrivaltime",
    ):
        v = lower.get(k)
        if v is None:
            continue
        try:
            if isinstance(v, (int, float)) and v > 1e11:
                return datetime.utcfromtimestamp(v / 1000.0)
            ts = str(v).strip()
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            elif ts.endswith("+0000"):
                ts = ts[:-5] + "+00:00"
            elif re.match(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}", ts):
                ts = re.sub(r"^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})", r"\1T\2", ts)
            dt = datetime.fromisoformat(ts)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except (ValueError, TypeError, OSError):
            continue
    return None


async def _get_sync_meta_value(db: AsyncSession, key: str) -> Optional[str]:
    r = await db.execute(select(SyncMetadata.value).where(SyncMetadata.key == key))
    row = r.first()
    return str(row[0]) if row and row[0] else None


async def _set_sync_meta_value(db: AsyncSession, key: str, value: str) -> None:
    r = await db.execute(select(SyncMetadata).where(SyncMetadata.key == key))
    row = r.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SyncMetadata(key=key, value=value))


async def _upsert_inbound_rows(db: AsyncSession, connection_id: int, rows: List[dict]) -> int:
    """Upsert OC inbound rows into oc_inbound_orders. Returns number of input rows processed."""
    now = datetime.utcnow()
    n = 0
    for r in rows:
        seller = str(r.get("seller_inbound_number") or "").strip()
        oc = r.get("oc_inbound_number")
        dk = _inbound_dedup_key(seller, oc)
        if dk in ("", "::"):
            continue
        status_val = str(r.get("status") or "").strip()
        status_lower = status_val.lower()
        indicates_putaway = _status_indicates_putaway(status_lower)
        indicates_arrived = _status_indicates_arrived(status_lower)
        raw = r.get("raw_payload")
        # "Create time" in UI should be the first time we saw this inbound in sync.
        # Keep inbound_at stable after first insert.
        inbound_at = now
        raw_s = json.dumps(raw, ensure_ascii=False) if raw is not None else None
        new_putaway_qty = int(r.get("put_away_qty") or 0)
        existing = None
        existing_r = await db.execute(
            select(OCInboundOrder).where(
                OCInboundOrder.connection_id == connection_id,
                OCInboundOrder.dedup_key == dk,
            )
        )
        existing = existing_r.scalar_one_or_none()

        # Fallback matching: inbound identifiers can arrive incomplete in earlier syncs
        # (e.g. no OC number yet), then become populated later. In that case dedup_key changes;
        # match by stable identifiers so we update the same row instead of creating duplicates.
        if existing is None and (oc or seller):
            filters = []
            if oc:
                filters.append(func.lower(OCInboundOrder.oc_inbound_number) == str(oc).strip().lower())
            if seller:
                filters.append(
                    func.lower(OCInboundOrder.seller_inbound_number) == str(seller).strip().lower()
                )
            if filters:
                existing_r = await db.execute(
                    select(OCInboundOrder).where(
                        OCInboundOrder.connection_id == connection_id,
                        or_(*filters),
                    )
                )
                existing = existing_r.scalar_one_or_none()
        if existing:
            prev_putaway_qty = int(existing.put_away_qty or 0)
            prev_status_lower = str(existing.status or "").lower()
            # Eligibility uses first-seen before mutating inbound_at (backfill would look "new").
            first_seen_for_est = existing.inbound_at or existing.synced_at
            eligible_est = _eligible_for_inbound_stage_estimates(now, first_seen_for_est)
            existing.dedup_key = dk
            existing.seller_inbound_number = seller
            existing.oc_inbound_number = oc
            existing.status = r.get("status")
            existing.warehouse_code = r.get("warehouse_code")
            existing.region = r.get("region")
            existing.shipping_method = r.get("shipping_method")
            existing.sku_qty = int(r.get("sku_qty") or 0)
            existing.put_away_qty = new_putaway_qty
            if existing.inbound_at is None and inbound_at:
                existing.inbound_at = inbound_at
            if eligible_est and _should_set_putaway_at(
                existing.putaway_at,
                prev_putaway_qty,
                new_putaway_qty,
                prev_status_lower,
                status_lower,
            ):
                existing.putaway_at = now
            if eligible_est and _should_set_arrived_at(
                existing.arrived_at,
                prev_putaway_qty,
                new_putaway_qty,
                prev_status_lower,
                status_lower,
            ):
                existing.arrived_at = now
            if raw_s:
                existing.raw_payload = raw_s
            existing.synced_at = now
        else:
            # First time we see this row: do not stamp putaway_at / arrived_at with utcnow().
            # Those columns are sync-time guesses and read as false warehouse dates when the
            # order was already terminal (Put away) before EvampOps ever cached it. Real times
            # must come from OC raw_payload via _extract_inbound_ui_times; transitions are handled
            # on the update branch above when eligible_est applies.
            db.add(
                OCInboundOrder(
                    connection_id=connection_id,
                    dedup_key=dk,
                    seller_inbound_number=seller,
                    oc_inbound_number=oc,
                    status=r.get("status"),
                    warehouse_code=r.get("warehouse_code"),
                    region=r.get("region"),
                    shipping_method=r.get("shipping_method"),
                    sku_qty=int(r.get("sku_qty") or 0),
                    put_away_qty=new_putaway_qty,
                    inbound_at=inbound_at,
                    putaway_at=None,
                    arrived_at=None,
                    raw_payload=raw_s,
                    synced_at=now,
                )
            )
        n += 1
    return n


@router.get("/summary", response_model=InventoryStatusSummary)
async def get_inventory_status_summary(db: AsyncSession = Depends(get_db)):
    conn_result = await db.execute(
        select(OCConnection).where(OCConnection.is_active == True).limit(1)
    )
    connection = conn_result.scalar_one_or_none()

    creds_result = await db.execute(
        select(APICredential.key_name).where(
            APICredential.service_name == "oc",
            APICredential.is_active == True,
        )
    )
    keys = [r[0] for r in creds_result.all()]
    required = {"client_id", "client_secret", "refresh_token"}
    has_required = required.issubset(set(keys))

    last_sync_result = await db.execute(
        select(OCSkuMapping).order_by(OCSkuMapping.last_synced_at.desc()).limit(1)
    )
    last_sync_row = last_sync_result.scalar_one_or_none()
    count_result = await db.execute(select(OCSkuMapping))
    mapping_count = len(count_result.scalars().all())

    return InventoryStatusSummary(
        connection=connection,
        credentials_present=keys,
        has_required_credentials=has_required,
        mapping_count=mapping_count,
        last_sync_at=last_sync_row.last_synced_at if last_sync_row else None,
    )


@router.put("/connection", response_model=OCConnectionResponse)
async def upsert_oc_connection(
    req: OCConnectionUpsertRequest, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(OCConnection).limit(1))
    existing = result.scalar_one_or_none()
    if existing:
        existing.name = req.name.strip() or "OC"
        existing.region = req.region.strip().upper() or "UK"
        existing.environment = req.environment
        existing.oauth_base_url = req.oauth_base_url.strip().rstrip("/")
        existing.api_base_url = req.api_base_url.strip().rstrip("/")
        existing.signature_mode = req.signature_mode
        existing.is_active = req.is_active
        await db.commit()
        await db.refresh(existing)
        return existing

    row = OCConnection(
        name=req.name.strip() or "OC",
        region=req.region.strip().upper() or "UK",
        environment=req.environment,
        oauth_base_url=req.oauth_base_url.strip().rstrip("/"),
        api_base_url=req.api_base_url.strip().rstrip("/"),
        signature_mode=req.signature_mode,
        is_active=req.is_active,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


@router.post("/oauth/authorize-url", response_model=OCAuthUrlResponse)
async def build_oc_authorize_url(
    req: OCAuthUrlRequest, db: AsyncSession = Depends(get_db)
):
    try:
        url = await oc_build_authorize_url(db, req.redirect_uri, req.state)
        return OCAuthUrlResponse(authorize_url=url)
    except (OCConfigError, OCAPIError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Build authorize URL failed: {e}")


@router.post("/oauth/exchange-code", response_model=OCExchangeCodeResponse)
async def exchange_oc_authorization_code(
    req: OCExchangeCodeRequest, db: AsyncSession = Depends(get_db)
):
    try:
        token_payload = await oc_exchange_code_for_tokens(db, req.code, req.redirect_uri)
    except (OCConfigError, OCAPIError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Code exchange failed: {e}")

    refresh_token = str(token_payload.get("refresh_token") or "").strip()
    if not refresh_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="OC token response did not include refresh_token.",
        )

    encrypted_value = encryption_service.encrypt(refresh_token)
    result = await db.execute(
        select(APICredential).where(
            APICredential.service_name == "oc",
            APICredential.key_name == "refresh_token",
        )
    )
    existing = result.scalar_one_or_none()
    if existing:
        existing.encrypted_value = encrypted_value
        existing.is_active = True
    else:
        db.add(
            APICredential(
                service_name="oc",
                key_name="refresh_token",
                encrypted_value=encrypted_value,
                is_active=True,
            )
        )
    await db.commit()
    expires_val = token_payload.get("expires_in")
    try:
        expires_in = int(expires_val) if expires_val is not None else None
    except Exception:  # noqa: BLE001
        expires_in = None
    return OCExchangeCodeResponse(
        access_token_received=bool(token_payload.get("access_token")),
        refresh_token_stored=True,
        expires_in=expires_in,
    )


@router.post("/test-connection", response_model=ConnectionTestResponse)
async def test_oc_connection(db: AsyncSession = Depends(get_db)):
    try:
        data = await oc_test_connection(db)
        return ConnectionTestResponse(
            ok=True,
            detail="Connection OK",
            region=data.get("region"),
            environment=data.get("environment"),
            service_count=data.get("service_count"),
        )
    except (OCConfigError, OCAPIError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OC test failed: {e}")


async def execute_oc_sku_mappings_sync(db: AsyncSession) -> SyncSkuResponse:
    """OC SKU mapping + inventory snapshot upsert (API and scheduled refresh)."""
    conn_result = await db.execute(
        select(OCConnection).where(OCConnection.is_active == True).limit(1)
    )
    connection = conn_result.scalar_one_or_none()
    if not connection:
        raise HTTPException(status_code=400, detail="No active OC connection configured.")
    try:
        rows = await oc_sync_sku_mappings(db)
        inventory_rows_data = await oc_fetch_inventory_rows(db)
    except (OCConfigError, OCAPIError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OC sync failed: {e}") from e

    await db.execute(delete(OCSkuMapping).where(OCSkuMapping.connection_id == connection.id))
    await db.execute(delete(OCSkuInventory).where(OCSkuInventory.connection_id == connection.id))
    synced = 0
    skipped = 0
    inventory_rows = 0
    for r in rows:
        sku_code = (r.get("sku_code") or "").strip()
        mfskuid = (r.get("mfskuid") or "").strip()
        if not sku_code or not mfskuid:
            skipped += 1
            continue
        db.add(
            OCSkuMapping(
                connection_id=connection.id,
                sku_code=sku_code,
                seller_skuid=(r.get("seller_skuid") or sku_code).strip(),
                reference_skuid=(r.get("reference_skuid") or sku_code).strip(),
                mfskuid=mfskuid,
                service_region=r.get("service_region"),
                raw_payload=json.dumps(r.get("raw_payload") or {}, ensure_ascii=False),
            )
        )
        synced += 1
    for inv in inventory_rows_data:
        db.add(
            OCSkuInventory(
                connection_id=connection.id,
                mfskuid=str(inv.get("mfskuid") or "").strip(),
                service_region=str(inv.get("service_region") or connection.region or "UK").strip() or "UK",
                available=int(inv.get("available") or 0),
                in_transit=int(inv.get("in_transit") or 0),
                received=int(inv.get("received") or 0),
                reserved_allocated=int(inv.get("reserved_allocated") or 0),
                reserved_hold=int(inv.get("reserved_hold") or 0),
                reserved_vas=int(inv.get("reserved_vas") or 0),
                suspend=int(inv.get("suspend") or 0),
                unfulfillable=int(inv.get("unfulfillable") or 0),
            )
        )
        inventory_rows += 1
    await db.commit()
    return SyncSkuResponse(synced=synced, skipped=skipped, inventory_rows=inventory_rows)


@router.post("/sync-sku-mappings", response_model=SyncSkuResponse)
async def sync_oc_sku_mappings(db: AsyncSession = Depends(get_db)):
    return await execute_oc_sku_mappings_sync(db)


@router.get("/sku-mappings", response_model=List[SkuMappingResponse])
async def list_sku_mappings(
    sku: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    query = select(OCSkuMapping).order_by(OCSkuMapping.sku_code.asc())
    if sku and sku.strip():
        query = query.where(OCSkuMapping.sku_code == sku.strip())
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/inventory", response_model=List[OCSkuInventoryResponse])
async def list_oc_inventory(
    db: AsyncSession = Depends(get_db),
):
    inv_result = await db.execute(select(OCSkuInventory).order_by(OCSkuInventory.mfskuid.asc()))
    rows = list(inv_result.scalars().all())
    map_result = await db.execute(select(OCSkuMapping))
    mappings = list(map_result.scalars().all())
    by_mf: dict[str, str] = {}
    for m in mappings:
        key = (m.mfskuid or "").strip().lower()
        if key and key not in by_mf:
            by_mf[key] = (m.seller_skuid or "").strip()

    seller_skus = sorted({v for v in by_mf.values() if v})
    sold_by_sku_3m: dict[str, int] = {}
    sold_by_sku_1m: dict[str, int] = {}
    if seller_skus:
        # Match Sales Analytics date presets (frontend `lastNDaysFrom(n)`): from = today − (n−1) through today inclusive.
        today = date.today()
        from_3m = today - timedelta(days=89)  # 90-day window (3m preset)
        from_1m = today - timedelta(days=29)  # 30-day window (1m preset)
        sales_stmt = (
            select(
                LineItem.sku.label("sku"),
                func.coalesce(func.sum(LineItem.quantity), 0).label("sold_3m"),
                func.coalesce(
                    func.sum(
                        case(
                            (Order.date >= from_1m, LineItem.quantity),
                            else_=0,
                        )
                    ),
                    0,
                ).label("sold_1m"),
            )
            .select_from(LineItem)
            .join(Order, Order.order_id == LineItem.order_id)
            .where(
                LineItem.sku.in_(seller_skus),
                Order.cancel_status != "CANCELED",
                Order.date >= from_3m,
                Order.date <= today,
            )
            .group_by(LineItem.sku)
        )
        sales_result = await db.execute(sales_stmt)
        for s in sales_result.all():
            sku_key = (s.sku or "").strip()
            sold_by_sku_3m[sku_key] = int(s.sold_3m or 0)
            sold_by_sku_1m[sku_key] = int(s.sold_1m or 0)

    flat: List[OCSkuInventoryResponse] = []
    for r in rows:
        seller_sku = by_mf.get((r.mfskuid or "").strip().lower()) or None
        flat.append(
            OCSkuInventoryResponse(
                id=r.id,
                seller_skuid=seller_sku,
                mfskuid=r.mfskuid,
                service_region=r.service_region,
                available=r.available,
                in_transit=r.in_transit,
                received=r.received,
                reserved_allocated=r.reserved_allocated,
                reserved_hold=r.reserved_hold,
                reserved_vas=r.reserved_vas,
                suspend=r.suspend,
                unfulfillable=r.unfulfillable,
                sold_3m_units=sold_by_sku_3m.get(seller_sku or "", 0),
                sold_1m_units=sold_by_sku_1m.get(seller_sku or "", 0),
                synced_at=r.synced_at,
            )
        )

    # One row per seller SKU: sum OC quantities across regions (UK, US-South, etc.).
    by_seller: dict[str, List[OCSkuInventoryResponse]] = defaultdict(list)
    unmapped: List[OCSkuInventoryResponse] = []
    for p in flat:
        sk = (p.seller_skuid or "").strip()
        if sk:
            by_seller[sk].append(p)
        else:
            unmapped.append(p)

    payload: List[OCSkuInventoryResponse] = []
    for sk in sorted(by_seller.keys(), key=lambda x: x.lower()):
        items = by_seller[sk]
        mfs_joined = ",".join(
            sorted({(p.mfskuid or "").strip() for p in items if (p.mfskuid or "").strip()})
        )
        regions_joined = ",".join(
            sorted({(p.service_region or "").strip() for p in items if (p.service_region or "").strip()})
        )
        payload.append(
            OCSkuInventoryResponse(
                id=min(p.id for p in items),
                seller_skuid=sk,
                mfskuid=mfs_joined or (items[0].mfskuid if items else ""),
                service_region=regions_joined or (items[0].service_region if items else ""),
                available=sum(p.available for p in items),
                in_transit=sum(p.in_transit for p in items),
                received=sum(p.received for p in items),
                reserved_allocated=sum(p.reserved_allocated for p in items),
                reserved_hold=sum(p.reserved_hold for p in items),
                reserved_vas=sum(p.reserved_vas for p in items),
                suspend=sum(p.suspend for p in items),
                unfulfillable=sum(p.unfulfillable for p in items),
                sold_3m_units=items[0].sold_3m_units,
                sold_1m_units=items[0].sold_1m_units,
                synced_at=max(p.synced_at for p in items),
            )
        )
    payload.extend(sorted(unmapped, key=lambda p: (p.mfskuid or "").lower()))
    return payload


async def execute_oc_inbound_sync(db: AsyncSession, full: bool) -> InboundSyncResponse:
    """Pull inbound orders from OrangeConnex into `oc_inbound_orders` (API and scheduled refresh)."""
    cid = await _active_oc_connection_id(db)
    if not cid:
        raise HTTPException(status_code=400, detail="No active OC connection configured.")
    end = datetime.now(timezone.utc).replace(tzinfo=None)
    if full:
        date_from = INBOUND_STATUS_CHART_FROM
        logger.info("OC inbound DB sync: FULL from %s to %s", date_from, end.date())
    else:
        raw_last = await _get_sync_meta_value(db, SYNC_META_INBOUND_LAST)
        if raw_last:
            try:
                last = datetime.fromisoformat(raw_last.replace("Z", "+00:00")).replace(tzinfo=None)
                overlap_start = last - timedelta(days=INBOUND_INCREMENTAL_OVERLAP_DAYS)
                floor = datetime.combine(INBOUND_STATUS_CHART_FROM, dt_time.min)
                date_from = max(floor, overlap_start).date()
            except (ValueError, TypeError):
                date_from = INBOUND_STATUS_CHART_FROM
        else:
            date_from = INBOUND_STATUS_CHART_FROM
        logger.info("OC inbound DB sync: incremental from %s to %s", date_from, end.date())

    processed = 0
    try:
        rows = await oc_fetch_inbound_orders(
            db,
            months_back=6,
            date_from=date_from,
            date_to=end,
        )
        logger.info("OC inbound DB sync: fetched %d unique orders from API, upserting", len(rows))
        processed = await _upsert_inbound_rows(db, cid, rows)
        await _set_sync_meta_value(db, SYNC_META_INBOUND_LAST, datetime.now(timezone.utc).isoformat())
        await db.commit()
        logger.info("OC inbound DB sync: committed %d rows", processed)
    except (OCConfigError, OCAPIError) as e:
        await db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        await db.rollback()
        logger.exception("OC inbound DB sync failed: %s", e)
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OC inbound sync failed: {e}") from e

    return InboundSyncResponse(
        synced=processed,
        message="Inbound orders cached. Charts and tables read from the database.",
        full=full,
    )


@router.post("/inbound-orders/sync", response_model=InboundSyncResponse)
async def sync_oc_inbound_orders_to_db(
    full: bool = Query(False, description="If true, re-fetch from 2024-01-01 through now. If false, incremental since last sync (min 7-day overlap)."),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull inbound orders from OrangeConnex and upsert into `oc_inbound_orders`.
    Logs each chunk to the application logger. Use `full=true` for a complete backfill.
    """
    return await execute_oc_inbound_sync(db, full)


@router.get("/inbound-orders/status-summary", response_model=InboundOrderStatusSummaryResponse)
async def inbound_orders_status_summary(db: AsyncSession = Depends(get_db)):
    """
    Count inbound orders by status from the cached `oc_inbound_orders` table (fast).
    Run POST /inbound-orders/sync to refresh from OrangeConnex.
    """
    cid = await _active_oc_connection_id(db)
    if not cid:
        return InboundOrderStatusSummaryResponse(
            from_date=INBOUND_STATUS_CHART_FROM.isoformat(),
            to_date=date.today().isoformat(),
            total_orders=0,
            slices=[],
            last_sync_at=None,
        )

    status_expr = func.coalesce(OCInboundOrder.status, "(no status)")
    stmt = (
        select(status_expr, func.count())
        .where(OCInboundOrder.connection_id == cid, _inbound_not_canceled_sql())
        .group_by(status_expr)
    )
    result = await db.execute(stmt)
    counts: dict[str, int] = {}
    total = 0
    for st_val, cnt in result.all():
        k = str(st_val) if st_val is not None else "(no status)"
        c = int(cnt)
        counts[k] = c
        total += c
    slices = [
        InboundOrderStatusSlice(status=k, count=v)
        for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    ]
    last_sync = await _get_sync_meta_value(db, SYNC_META_INBOUND_LAST)
    return InboundOrderStatusSummaryResponse(
        from_date=INBOUND_STATUS_CHART_FROM.isoformat(),
        to_date=date.today().isoformat(),
        total_orders=total,
        slices=slices,
        last_sync_at=last_sync,
    )


@router.get("/inbound-orders", response_model=List[OCInboundOrderResponse])
async def list_oc_inbound_orders(
    months_back: int = 6,
    include_raw: bool = Query(
        False,
        description="Include full OC JSON per row (raw_payload). Larger response; use to inspect all API fields.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """List cached inbound orders; approximate window using `months_back` (30-day months)."""
    cid = await _active_oc_connection_id(db)
    if not cid:
        return []

    cutoff = date.today() - timedelta(days=max(months_back, 1) * 30)
    cutoff_dt = datetime.combine(cutoff, dt_time.min)
    coalesced = func.coalesce(OCInboundOrder.inbound_at, OCInboundOrder.synced_at)
    stmt = (
        select(OCInboundOrder)
        .where(
            OCInboundOrder.connection_id == cid,
            coalesced >= cutoff_dt,
            _inbound_not_canceled_sql(),
        )
        .order_by(coalesced.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    payload: List[OCInboundOrderResponse] = []
    for r in rows:
        raw_parsed: Optional[Dict[str, Any]] = None
        if r.raw_payload:
            try:
                parsed = json.loads(r.raw_payload)
                raw_parsed = parsed if isinstance(parsed, dict) else None
            except (json.JSONDecodeError, TypeError):
                raw_parsed = None
        # Older rows may have inbound_at unset; fall back to synced_at so CREATE TIME is always populated.
        create_s, putaway_s, arrived_s = _extract_inbound_ui_times(
            raw_parsed,
            r.inbound_at or r.synced_at,
            putaway_at_db=r.putaway_at,
            arrived_at_db=r.arrived_at,
            status_from_row=r.status,
        )
        raw_obj = raw_parsed if include_raw else None
        payload.append(
            OCInboundOrderResponse(
                seller_inbound_number=r.seller_inbound_number or "",
                oc_inbound_number=r.oc_inbound_number,
                status=r.status,
                warehouse_code=r.warehouse_code,
                region=r.region,
                shipping_method=r.shipping_method,
                sku_qty=r.sku_qty,
                put_away_qty=r.put_away_qty,
                inbound_at=r.inbound_at,
                synced_at=r.synced_at,
                create_time=create_s,
                putaway_time=putaway_s,
                arrived_time=arrived_s,
                raw=raw_obj,
            )
        )
    return payload


@router.get("/inbound-orders/status-filter", response_model=InboundStatusFilterResponse)
async def get_inbound_status_filter(db: AsyncSession = Depends(get_db)):
    """Persisted Status column filter (hidden status values). Stored in sync_metadata."""
    raw = await _get_sync_meta_value(db, SYNC_META_INBOUND_STATUS_FILTER)
    if not raw or not str(raw).strip():
        return InboundStatusFilterResponse(excluded=[])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return InboundStatusFilterResponse(excluded=[])
    if isinstance(data, dict):
        ex = data.get("excluded")
        if isinstance(ex, list) and all(isinstance(x, str) for x in ex):
            return InboundStatusFilterResponse(excluded=ex)
    return InboundStatusFilterResponse(excluded=[])


@router.put("/inbound-orders/status-filter", response_model=InboundStatusFilterResponse)
async def put_inbound_status_filter(
    body: InboundStatusFilterPut,
    db: AsyncSession = Depends(get_db),
):
    payload = json.dumps({"excluded": body.excluded}, ensure_ascii=False)
    await _set_sync_meta_value(db, SYNC_META_INBOUND_STATUS_FILTER, payload)
    await db.commit()
    return InboundStatusFilterResponse(excluded=body.excluded)


@router.get("/inbound-orders/lookup", response_model=InboundOrderLookupResponse)
async def lookup_oc_inbound_order(
    request: Request,
    oc_inbound_number: str = Query(
        ...,
        min_length=5,
        max_length=200,
        description="OC inbound number, e.g. OCI5GB08513638",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    Transparency endpoint: one cached inbound by OC number (no date window).
    Use this to inspect raw OC JSON and how create/putaway/arrived were derived.
    """
    cid = await _active_oc_connection_id(db)
    if not cid:
        raise HTTPException(status_code=400, detail="No active OC connection configured.")

    oc = oc_inbound_number.strip()
    stmt = (
        select(OCInboundOrder)
        .where(
            OCInboundOrder.connection_id == cid,
            func.lower(OCInboundOrder.oc_inbound_number) == oc.lower(),
        )
        .limit(1)
    )
    result = await db.execute(stmt)
    r = result.scalar_one_or_none()
    if not r:
        raise HTTPException(
            status_code=404,
            detail=f"No cached inbound order with oc_inbound_number={oc!r}. Run POST /inbound-orders/sync or widen data.",
        )

    raw_parsed: Optional[Dict[str, Any]] = None
    if r.raw_payload:
        try:
            parsed = json.loads(r.raw_payload)
            raw_parsed = parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, TypeError):
            raw_parsed = None

    # Older rows may have inbound_at unset; fall back to synced_at so CREATE TIME is always populated.
    create_s, putaway_s, arrived_s = _extract_inbound_ui_times(
        raw_parsed,
        r.inbound_at or r.synced_at,
        putaway_at_db=r.putaway_at,
        arrived_at_db=r.arrived_at,
        status_from_row=r.status,
    )

    return InboundOrderLookupResponse(
        request_url=str(request.url),
        oc_inbound_number=r.oc_inbound_number or oc,
        seller_inbound_number=r.seller_inbound_number or None,
        status=r.status,
        warehouse_code=r.warehouse_code,
        region=r.region,
        shipping_method=r.shipping_method,
        sku_qty=r.sku_qty,
        put_away_qty=r.put_away_qty,
        inbound_at_db=r.inbound_at.isoformat() if r.inbound_at else None,
        synced_at_db=r.synced_at.isoformat() if r.synced_at else None,
        putaway_at_db=r.putaway_at.isoformat() if r.putaway_at else None,
        arrived_at_db=r.arrived_at.isoformat() if r.arrived_at else None,
        create_time=create_s,
        putaway_time=putaway_s,
        arrived_time=arrived_s,
        has_raw_payload=raw_parsed is not None,
        raw_oc_payload=raw_parsed,
    )


@router.get("/debug/inbound-detail-raw")
async def debug_inbound_detail_raw(
    oc_inbound_number: str = Query(
        ...,
        min_length=5,
        max_length=200,
        description="OC inbound number, e.g. OCI5DE07295030",
    ),
    window_start: Optional[date] = Query(
        None,
        description="Optional UTC date (inclusive). Use with window_end; max 7 days. Overrides anchor from DB.",
    ),
    window_end: Optional[date] = Query(
        None,
        description="Optional UTC date (inclusive). Use with window_start.",
    ),
    db: AsyncSession = Depends(get_db),
):
    """
    **Gated by `ALLOW_OC_INBOUND_DETAIL_DEBUG=true`.** Verbatim `POST /openapi/3pp/inbound/v1/detail`
    response (no merge). Compare `raw_response` to `GET /inbound-orders/lookup` → `raw_oc_payload`.

    Save: `curl -sS 'http://localhost:8000/api/inventory-status/debug/inbound-detail-raw?oc_inbound_number=...' -o /tmp/oc-detail-raw.json`
    """
    if not settings.ALLOW_OC_INBOUND_DETAIL_DEBUG:
        raise HTTPException(status_code=404, detail="Not found")
    if (window_start is None) ^ (window_end is None):
        raise HTTPException(
            status_code=400,
            detail="Provide both window_start and window_end (YYYY-MM-DD), or neither.",
        )
    try:
        return await oc_debug_inbound_detail_raw(
            db,
            oc_inbound_number.strip(),
            window_start=window_start,
            window_end=window_end,
        )
    except OCConfigError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OCAPIError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/debug-raw", response_model=OCRawDebugResponse)
async def debug_raw_oc_calls(
    service_region: str = "UK",
    mfskuid: str = "OC0000029222351",
    db: AsyncSession = Depends(get_db),
):
    try:
        return await oc_debug_raw_calls(db, service_region=service_region, mfskuid=mfskuid)
    except (OCConfigError, OCAPIError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OC debug failed: {e}")


@router.get("/debug-inbound-raw", response_model=OCInboundRawDebugResponse)
async def debug_inbound_raw_oc_calls(
    service_region: str = "UK",
    page: int = 1,
    page_size: int = 200,
    months_back: int = 6,
    db: AsyncSession = Depends(get_db),
):
    try:
        from app.services.oc_client import oc_debug_inbound_orders_calls

        return await oc_debug_inbound_orders_calls(
            db,
            service_region=service_region,
            page=max(page, 1),
            page_size=min(max(page_size, 1), 500),
            months_back=months_back,
        )
    except (OCConfigError, OCAPIError) as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OC inbound debug failed: {e}")
