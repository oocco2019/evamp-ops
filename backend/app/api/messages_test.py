"""
Messages-Test API: router draft, known-issues CRUD, follow-up list.
Isolated from legacy Messages compose path.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import httpx

from app.core.database import get_db
from app.models.messages import KnownIssue, MessageThread, ReplyStageTemplate, SyncMetadata
from app.services.ai_service import AIService
from app.services.reply_router import PROMISE_UPDATE_PATTERNS
from app.services.reply_router_compose import META_WHATSAPP, DEFAULT_WHATSAPP, compose_router_draft

logger = logging.getLogger(__name__)
router = APIRouter()


class RouterDraftRequest(BaseModel):
    extra_instructions: Optional[str] = Field(None, max_length=2000)
    force_stage: Optional[str] = Field(None, max_length=60)


class RouterDraftResponse(BaseModel):
    draft: Optional[str] = None
    tier: int
    router: Dict[str, Any]
    escalation: Optional[Dict[str, Any]] = None
    composition_id: Optional[int] = None


class KnownIssueOut(BaseModel):
    id: int
    issue_id: str
    symptom_keywords: List[str]
    applies_to_sku: str
    diagnosis: str
    confidence: str
    skip_to_action: str
    evidence_required: str
    disposal_note: bool
    batch_safe: bool
    requires_image: bool
    active: bool


class KnownIssueUpdate(BaseModel):
    symptom_keywords: Optional[List[str]] = None
    applies_to_sku: Optional[str] = None
    diagnosis: Optional[str] = None
    confidence: Optional[str] = None
    skip_to_action: Optional[str] = None
    evidence_required: Optional[str] = None
    disposal_note: Optional[bool] = None
    batch_safe: Optional[bool] = None
    requires_image: Optional[bool] = None
    active: Optional[bool] = None


class FollowUpItem(BaseModel):
    thread_id: str
    buyer_username: Optional[str] = None
    sku: Optional[str] = None
    ebay_order_id: Optional[str] = None
    last_message_at: Optional[str] = None
    days_stalled: int
    reason: str
    last_preview: Optional[str] = None


class CsSettingsOut(BaseModel):
    whatsapp: str


class CsSettingsUpdate(BaseModel):
    whatsapp: Optional[str] = None


def _issue_out(i: KnownIssue) -> KnownIssueOut:
    return KnownIssueOut(
        id=i.id,
        issue_id=i.issue_id,
        symptom_keywords=list(i.symptom_keywords or []),
        applies_to_sku=i.applies_to_sku,
        diagnosis=i.diagnosis,
        confidence=i.confidence,
        skip_to_action=i.skip_to_action,
        evidence_required=i.evidence_required,
        disposal_note=i.disposal_note,
        batch_safe=i.batch_safe,
        requires_image=i.requires_image,
        active=i.active,
    )


@router.post("/threads/{thread_id}/draft", response_model=RouterDraftResponse)
async def router_draft(
    thread_id: str,
    body: RouterDraftRequest,
    db: AsyncSession = Depends(get_db),
):
    from app.api.messages import _find_order_for_buyer

    result = await db.execute(
        select(MessageThread)
        .where(MessageThread.thread_id == thread_id)
        .options(selectinload(MessageThread.messages))
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    msgs = sorted(thread.messages, key=lambda m: m.ebay_created_at or datetime.min)
    ebay_order_id = thread.ebay_order_id
    buyer_name = thread.buyer_username
    if not buyer_name:
        for m in msgs:
            if m.sender_type == "buyer" and m.sender_username:
                buyer_name = m.sender_username
                break
    if not ebay_order_id and buyer_name:
        ebay_order_id = await _find_order_for_buyer(db, buyer_name)

    ai = AIService(db)

    async def _gen(prompt: str, context: dict) -> str:
        return await ai.generate_message(prompt, context)

    try:
        out = await compose_router_draft(
            db,
            thread=thread,
            messages=list(msgs),
            ebay_order_id=ebay_order_id,
            extra_instructions=body.extra_instructions,
            ai_generate=_gen,
            force_stage=body.force_stage,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except httpx.HTTPStatusError as e:
        logger.warning("Router draft AI error: %s", e)
        raise HTTPException(status_code=502, detail=f"AI provider error: {e}") from e
    except Exception as e:
        logger.exception("Router draft failed")
        raise HTTPException(status_code=500, detail=f"Draft failed: {e}") from e

    meta_key = f"last_composition:{thread_id}"
    meta = await db.get(SyncMetadata, meta_key)
    cid = out.get("composition_id")
    if cid is not None:
        if meta:
            meta.value = str(cid)
        else:
            db.add(SyncMetadata(key=meta_key, value=str(cid)))
    await db.commit()
    return RouterDraftResponse(
        draft=out.get("draft"),
        tier=int(out["tier"]),
        router=out["router"],
        escalation=out.get("escalation"),
        composition_id=cid,
    )


@router.get("/known-issues", response_model=List[KnownIssueOut])
async def list_known_issues(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(KnownIssue).order_by(KnownIssue.issue_id))
    return [_issue_out(i) for i in result.scalars().all()]


@router.patch("/known-issues/{issue_id}", response_model=KnownIssueOut)
async def update_known_issue(
    issue_id: str,
    body: KnownIssueUpdate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(KnownIssue).where(KnownIssue.issue_id == issue_id))
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Known issue not found")
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(row, k, v)
    row.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(row)
    return _issue_out(row)


@router.get("/settings", response_model=CsSettingsOut)
async def get_cs_settings(db: AsyncSession = Depends(get_db)):
    meta = await db.get(SyncMetadata, META_WHATSAPP)
    return CsSettingsOut(whatsapp=(meta.value if meta and meta.value else DEFAULT_WHATSAPP))


@router.put("/settings", response_model=CsSettingsOut)
async def put_cs_settings(body: CsSettingsUpdate, db: AsyncSession = Depends(get_db)):
    if body.whatsapp is not None:
        meta = await db.get(SyncMetadata, META_WHATSAPP)
        val = body.whatsapp.strip() or DEFAULT_WHATSAPP
        if meta:
            meta.value = val
        else:
            db.add(SyncMetadata(key=META_WHATSAPP, value=val))
        await db.commit()
    return await get_cs_settings(db)


@router.get("/follow-ups", response_model=List[FollowUpItem])
async def list_follow_ups(
    promise_days: int = Query(3, ge=1, le=30),
    stalled_days: int = Query(5, ge=1, le=60),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """
    Threads where last message is seller/ebay and stalled, or seller promised an update.
    """
    now = datetime.utcnow()
    # Load recent threads with messages
    result = await db.execute(
        select(MessageThread)
        .options(selectinload(MessageThread.messages))
        .order_by(MessageThread.last_message_at.desc().nullslast())
        .limit(400)
    )
    threads = list(result.scalars().unique().all())
    promise_re = re.compile("|".join(f"(?:{p})" for p in PROMISE_UPDATE_PATTERNS), re.I)

    out: List[FollowUpItem] = []
    for t in threads:
        msgs = sorted(t.messages, key=lambda m: m.ebay_created_at or datetime.min)
        if not msgs:
            continue
        last = msgs[-1]
        last_type = (last.sender_type or "").lower()
        if last_type not in {"seller", "ebay", "system"}:
            continue
        last_at = last.ebay_created_at or t.last_message_at or now
        age_days = max(0, (now - last_at).days)
        seller_texts = [
            (m.content or "")
            for m in msgs
            if (m.sender_type or "").lower() == "seller"
        ]
        promised = any(promise_re.search(txt) for txt in seller_texts[-5:])
        reason = None
        if promised and age_days >= promise_days:
            reason = f"promised_update>{promise_days}d"
        elif age_days >= stalled_days:
            reason = f"stalled>{stalled_days}d"
        if not reason:
            continue
        out.append(
            FollowUpItem(
                thread_id=t.thread_id,
                buyer_username=t.buyer_username,
                sku=t.sku,
                ebay_order_id=t.ebay_order_id,
                last_message_at=last_at.isoformat() if last_at else None,
                days_stalled=age_days,
                reason=reason,
                last_preview=(t.last_message_preview or (last.content or ""))[:180],
            )
        )
        if len(out) >= limit:
            break
    return out


@router.get("/stage-templates")
async def list_stage_templates(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ReplyStageTemplate).order_by(ReplyStageTemplate.stage_key))
    return [
        {"stage_key": r.stage_key, "instruction": r.instruction}
        for r in result.scalars().all()
    ]
