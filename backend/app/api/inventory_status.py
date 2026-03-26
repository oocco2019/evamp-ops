"""
Inventory status API (OrangeConnex, read-only).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, date, timedelta, timezone, time as dt_time
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.settings import APICredential, OCConnection, OCSkuMapping, OCSkuInventory, OCInboundOrder
from app.models.messages import SyncMetadata
from app.models.stock import LineItem, Order
from app.core.security import encryption_service
from app.services.oc_client import (
    OCAPIError,
    OCConfigError,
    oc_build_authorize_url,
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


class OCInboundOrderResponse(BaseModel):
    seller_inbound_number: str
    oc_inbound_number: Optional[str] = None
    status: Optional[str] = None
    warehouse_code: Optional[str] = None
    region: Optional[str] = None
    shipping_method: Optional[str] = None
    sku_qty: int = 0
    put_away_qty: int = 0


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


# Earliest date for historic inbound status chart (inclusive, UTC).
INBOUND_STATUS_CHART_FROM = date(2024, 1, 1)


async def _active_oc_connection_id(db: AsyncSession) -> Optional[int]:
    r = await db.execute(select(OCConnection.id).where(OCConnection.is_active == True).limit(1))
    row = r.first()
    return int(row[0]) if row else None


def _inbound_dedup_key(seller: str, oc: Optional[str]) -> str:
    s = (seller or "").strip().lower()
    o = (oc or "").strip().lower()
    return f"{o}::{s}"


def _parse_inbound_at(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, dict):
        return None
    lower = {str(k).lower(): v for k, v in raw.items()}
    for k in ("createtime", "createdtime", "inboundcreatetime", "createddate", "inboundcreatedtime"):
        v = lower.get(k)
        if v is None:
            continue
        try:
            ts = str(v).strip()
            if ts.endswith("Z"):
                ts = ts[:-1] + "+00:00"
            dt = datetime.fromisoformat(ts)
            return dt.replace(tzinfo=None) if dt.tzinfo else dt
        except (ValueError, TypeError):
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
        raw = r.get("raw_payload")
        inbound_at = _parse_inbound_at(raw) if isinstance(raw, dict) else None
        raw_s = json.dumps(raw, ensure_ascii=False) if raw is not None else None
        existing_r = await db.execute(
            select(OCInboundOrder).where(
                OCInboundOrder.connection_id == connection_id,
                OCInboundOrder.dedup_key == dk,
            )
        )
        existing = existing_r.scalar_one_or_none()
        if existing:
            existing.seller_inbound_number = seller
            existing.oc_inbound_number = oc
            existing.status = r.get("status")
            existing.warehouse_code = r.get("warehouse_code")
            existing.region = r.get("region")
            existing.shipping_method = r.get("shipping_method")
            existing.sku_qty = int(r.get("sku_qty") or 0)
            existing.put_away_qty = int(r.get("put_away_qty") or 0)
            if inbound_at:
                existing.inbound_at = inbound_at
            if raw_s:
                existing.raw_payload = raw_s
            existing.synced_at = now
        else:
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
                    put_away_qty=int(r.get("put_away_qty") or 0),
                    inbound_at=inbound_at,
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


@router.post("/sync-sku-mappings", response_model=SyncSkuResponse)
async def sync_oc_sku_mappings(db: AsyncSession = Depends(get_db)):
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
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"OC sync failed: {e}")

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
        today = date.today()
        cutoff_3m = today - timedelta(days=90)
        cutoff_1m = today - timedelta(days=30)
        sales_stmt = (
            select(
                LineItem.sku.label("sku"),
                func.coalesce(
                    func.sum(
                        case(
                            (Order.date >= cutoff_3m, LineItem.quantity),
                            else_=0,
                        )
                    ),
                    0,
                ).label("sold_3m"),
                func.coalesce(
                    func.sum(
                        case(
                            (Order.date >= cutoff_1m, LineItem.quantity),
                            else_=0,
                        )
                    ),
                    0,
                ).label("sold_1m"),
            )
            .select_from(LineItem)
            .join(Order, Order.order_id == LineItem.order_id)
            .where(LineItem.sku.in_(seller_skus), Order.cancel_status != "CANCELED")
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


@router.post("/inbound-orders/sync", response_model=InboundSyncResponse)
async def sync_oc_inbound_orders_to_db(
    full: bool = Query(False, description="If true, re-fetch from 2024-01-01 through now. If false, incremental since last sync (min 7-day overlap)."),
    db: AsyncSession = Depends(get_db),
):
    """
    Pull inbound orders from OrangeConnex and upsert into `oc_inbound_orders`.
    Logs each chunk to the application logger. Use `full=true` for a complete backfill.
    """
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
                overlap_start = last - timedelta(days=7)
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
        .where(OCInboundOrder.connection_id == cid)
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
        )
        .order_by(coalesced.desc())
    )
    result = await db.execute(stmt)
    rows = result.scalars().all()
    payload: List[OCInboundOrderResponse] = []
    for r in rows:
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
            )
        )
    return payload


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
