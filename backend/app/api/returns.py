"""Returns: multi-label A4 compose API."""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.services.label_compose.compose import (
    ComposeError,
    UploadedLabel,
    compose_labels,
    get_template,
    save_template_slots,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class ComposeResponse(BaseModel):
    pdf_base64: str
    preview_png_base64: str
    fingerprint: str
    slots: List[dict]
    arrangement_index: int
    arrangement_count: int
    cache_hit: bool


class TemplateUpdate(BaseModel):
    slots: List[dict] = Field(..., min_length=1)
    arrangement_index: int = 0


class TemplateResponse(BaseModel):
    fingerprint: str
    slots: Any
    arrangement_index: int
    updated_at: Optional[str] = None


@router.post("/compose", response_model=ComposeResponse)
async def compose(
    files: List[UploadFile] = File(...),
    arrangement_index: int = Form(0),
    slot_overrides: Optional[str] = Form(None),
    persist_cache: bool = Form(True),
    db: AsyncSession = Depends(get_db),
):
    """
    Compose any number of PDF/PNG shipping labels onto one A4 sheet.
    Returns base64 PDF plus slot coordinates for preview overlays.
    """
    if not files:
        raise HTTPException(status_code=400, detail="Upload at least one file.")

    uploads: list[UploadedLabel] = []
    for f in files:
        data = await f.read()
        uploads.append(
            UploadedLabel(
                filename=f.filename or "label",
                content_type=f.content_type,
                data=data,
            )
        )

    overrides = None
    if slot_overrides:
        try:
            parsed = json.loads(slot_overrides)
            if not isinstance(parsed, list):
                raise ValueError("slot_overrides must be a JSON array")
            overrides = parsed
        except (json.JSONDecodeError, ValueError) as e:
            raise HTTPException(status_code=400, detail=f"Invalid slot_overrides: {e}") from e

    try:
        result = await compose_labels(
            db,
            uploads,
            arrangement_index=arrangement_index,
            slot_overrides=overrides,
            persist_cache=persist_cache,
        )
    except ComposeError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    except Exception as e:
        logger.exception("compose failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Compose failed: {e}",
        ) from e

    return ComposeResponse(
        pdf_base64=result.pdf_base64,
        preview_png_base64=result.preview_png_base64,
        fingerprint=result.fingerprint,
        slots=result.slots,
        arrangement_index=result.arrangement_index,
        arrangement_count=result.arrangement_count,
        cache_hit=result.cache_hit,
    )


@router.put("/templates/{fingerprint}", response_model=TemplateResponse)
async def put_template(
    fingerprint: str,
    body: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        data = await save_template_slots(
            db, fingerprint, body.slots, body.arrangement_index
        )
    except ComposeError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message) from e
    return TemplateResponse(
        fingerprint=data["fingerprint"],
        slots=data["slots"],
        arrangement_index=data["arrangement_index"],
        updated_at=None,
    )


@router.get("/templates/{fingerprint}", response_model=TemplateResponse)
async def read_template(fingerprint: str, db: AsyncSession = Depends(get_db)):
    data = await get_template(db, fingerprint)
    if not data:
        raise HTTPException(status_code=404, detail="Template not found.")
    return TemplateResponse(**data)
