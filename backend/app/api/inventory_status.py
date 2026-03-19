"""
Inventory status API (OrangeConnex, read-only).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.settings import APICredential, OCConnection, OCSkuMapping, OCSkuInventory
from app.core.security import encryption_service
from app.services.oc_client import (
    OCAPIError,
    OCConfigError,
    oc_build_authorize_url,
    oc_debug_raw_calls,
    oc_exchange_code_for_tokens,
    oc_sync_sku_mappings,
    oc_test_connection,
)

router = APIRouter()


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
        inv = r.get("inventory") if isinstance(r.get("inventory"), dict) else None
        if inv:
            db.add(
                OCSkuInventory(
                    connection_id=connection.id,
                    mfskuid=mfskuid,
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
    query = select(OCSkuInventory).order_by(OCSkuInventory.mfskuid.asc())
    result = await db.execute(query)
    return result.scalars().all()


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
