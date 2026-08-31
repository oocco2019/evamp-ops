"""Orchestrate detect → fingerprint → cache/fit → render."""

from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import LabelComposeTemplate
from app.services.label_compose import MAX_FILES, MAX_UPLOAD_BYTES
from app.services.label_compose.detect import ContentBox, load_input_as_pdf_and_box
from app.services.label_compose.fingerprint import fingerprint_from_boxes
from app.services.label_compose.layout import (
    LabelInput,
    Slot,
    layout_for_variant,
    remap_slots_by_content_size,
    slots_from_overrides,
)
from app.services.label_compose.render import preview_png_base64, render_a4

logger = logging.getLogger(__name__)


@dataclass
class UploadedLabel:
    filename: str
    content_type: str | None
    data: bytes


@dataclass
class ComposeResult:
    pdf_base64: str
    preview_png_base64: str
    fingerprint: str
    slots: list[dict]
    arrangement_index: int
    arrangement_count: int
    cache_hit: bool


class ComposeError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _pack_result(
    pdf_bytes: bytes,
    *,
    fingerprint: str,
    slots: list[dict],
    arrangement_index: int,
    arrangement_count: int,
    cache_hit: bool,
) -> ComposeResult:
    return ComposeResult(
        pdf_base64=base64.b64encode(pdf_bytes).decode("ascii"),
        preview_png_base64=preview_png_base64(pdf_bytes),
        fingerprint=fingerprint,
        slots=slots,
        arrangement_index=arrangement_index,
        arrangement_count=arrangement_count,
        cache_hit=cache_hit,
    )


async def _get_template(db: AsyncSession, fingerprint: str) -> Optional[LabelComposeTemplate]:
    result = await db.execute(
        select(LabelComposeTemplate).where(LabelComposeTemplate.fingerprint == fingerprint)
    )
    return result.scalar_one_or_none()


async def _upsert_template(
    db: AsyncSession,
    fingerprint: str,
    slots: list[dict],
    arrangement_index: int,
) -> None:
    row = await _get_template(db, fingerprint)
    if row is None:
        row = LabelComposeTemplate(
            fingerprint=fingerprint,
            slots=slots,
            arrangement_index=arrangement_index,
            updated_at=datetime.utcnow(),
        )
        db.add(row)
    else:
        row.slots = slots
        row.arrangement_index = arrangement_index
        row.updated_at = datetime.utcnow()
    await db.commit()


def _prepare_labels(uploads: Sequence[UploadedLabel]) -> tuple[list[LabelInput], dict[int, bytes], list[ContentBox]]:
    if not uploads:
        raise ComposeError("Upload at least one PDF or PNG label.")
    if len(uploads) > MAX_FILES:
        raise ComposeError(f"Too many files (max {MAX_FILES}).")
    total = sum(len(u.data) for u in uploads)
    if total > MAX_UPLOAD_BYTES:
        raise ComposeError("Upload too large.")

    labels: list[LabelInput] = []
    pdfs: dict[int, bytes] = {}
    boxes: list[ContentBox] = []
    for i, up in enumerate(uploads):
        try:
            pdf_bytes, box = load_input_as_pdf_and_box(up.data, up.filename, up.content_type)
        except Exception as e:
            logger.exception("Failed to read label %s", up.filename)
            raise ComposeError(f"Could not read {up.filename or f'file {i+1}'}: {e}") from e
        labels.append(LabelInput(source_index=i, box=box))
        pdfs[i] = pdf_bytes
        boxes.append(box)
    return labels, pdfs, boxes


async def compose_labels(
    db: AsyncSession,
    uploads: Sequence[UploadedLabel],
    *,
    arrangement_index: int = 0,
    slot_overrides: Optional[list[dict]] = None,
    persist_cache: bool = True,
) -> ComposeResult:
    labels, pdfs, boxes = _prepare_labels(uploads)
    fingerprint = fingerprint_from_boxes(boxes)

    # Explicit drag overrides: use as-is; persist only when asked (Save layout)
    if slot_overrides:
        slots = slots_from_overrides(labels, slot_overrides)
        if not slots:
            raise ComposeError("Invalid slot overrides.")
        pdf_bytes = render_a4(pdfs, slots)
        slot_dicts = [s.to_dict() for s in slots]
        if persist_cache:
            await _upsert_template(db, fingerprint, slot_dicts, arrangement_index)
        return _pack_result(
            pdf_bytes,
            fingerprint=fingerprint,
            slots=slot_dicts,
            arrangement_index=arrangement_index,
            arrangement_count=max(1, arrangement_index + 1),
            cache_hit=False,
        )

    cache_hit = False

    # Cache only for variant 0 (initial / after Save). Regenerate uses index >= 1 and skips cache.
    cached = await _get_template(db, fingerprint)
    if cached and arrangement_index == 0 and cached.slots:
        try:
            raw_slots = cached.slots
            if isinstance(raw_slots, dict) and "slots" in raw_slots:
                raw_slots = raw_slots["slots"]
            cached_slots = [Slot.from_dict(s) for s in raw_slots]
            # Match by content size: fingerprint is order-invariant, source_index is not.
            fixed = remap_slots_by_content_size(cached_slots, labels)
            if fixed is not None:
                slots = fixed
                cache_hit = True
                pdf_bytes = render_a4(pdfs, slots)
                return _pack_result(
                    pdf_bytes,
                    fingerprint=fingerprint,
                    slots=[s.to_dict() for s in slots],
                    arrangement_index=int(cached.arrangement_index or 0),
                    arrangement_count=0,  # 0 = unlimited regenerate
                    cache_hit=True,
                )
        except Exception:
            logger.exception("Failed to apply cached template %s", fingerprint)
            cache_hit = False

    idx = max(0, int(arrangement_index))
    slots = layout_for_variant(labels, idx)
    if not slots:
        raise ComposeError(
            "Could not fit labels on a single A4 even after downscaling. "
            "Try fewer or smaller labels.",
            status_code=422,
        )
    pdf_bytes = render_a4(pdfs, slots)
    slot_dicts = [s.to_dict() for s in slots]

    # Only auto-cache the initial (best) layout — not every regenerate step
    if persist_cache and not cache_hit and idx == 0:
        await _upsert_template(db, fingerprint, slot_dicts, idx)

    return _pack_result(
        pdf_bytes,
        fingerprint=fingerprint,
        slots=slot_dicts,
        arrangement_index=idx,
        arrangement_count=0,  # unlimited
        cache_hit=False,
    )


async def save_template_slots(
    db: AsyncSession,
    fingerprint: str,
    slots: list[dict],
    arrangement_index: int = 0,
) -> dict[str, Any]:
    if not fingerprint or not slots:
        raise ComposeError("fingerprint and slots are required.")
    await _upsert_template(db, fingerprint, slots, arrangement_index)
    return {
        "fingerprint": fingerprint,
        "slots": slots,
        "arrangement_index": arrangement_index,
    }


async def get_template(db: AsyncSession, fingerprint: str) -> Optional[dict[str, Any]]:
    row = await _get_template(db, fingerprint)
    if not row:
        return None
    return {
        "fingerprint": row.fingerprint,
        "slots": row.slots,
        "arrangement_index": row.arrangement_index,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
