"""
Messages API (Phase 4-6): threads, draft, send.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, List, Optional

_sync_lock = asyncio.Lock()
_sync_in_progress = False
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, Integer, func
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import IntegrityError
from pydantic import BaseModel, Field
import httpx

from app.core.database import get_db
from app.core.config import settings
from app.models.messages import MessageThread, Message, AIInstruction, SyncMetadata, StyleProfile, Procedure, DraftFeedback
from app.models.stock import Order
from app.services.ai_service import AIService
from app.services.ebay_auth import get_ebay_access_token
from app.services.ebay_client import (
    fetch_message_conversations_page,
    fetch_all_conversations,
    fetch_all_conversation_messages,
    send_message as ebay_send_message,
    upload_image_for_message as ebay_upload_image,
    ALLOWED_IMAGE_EXTENSIONS,
    update_conversation_read,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# === Schemas ===

class MessageMediaItem(BaseModel):
    mediaName: str
    mediaType: str  # IMAGE, DOC, PDF, TXT
    mediaUrl: Optional[str] = None


class MessageResponse(BaseModel):
    message_id: str
    thread_id: str
    sender_type: str
    sender_username: Optional[str]
    subject: Optional[str]
    content: str
    media: Optional[List[MessageMediaItem]] = None
    is_read: bool
    detected_language: Optional[str]
    translated_content: Optional[str]
    ebay_created_at: str
    created_at: str

    model_config = {"from_attributes": True}


class ThreadSummary(BaseModel):
    thread_id: str
    buyer_username: Optional[str] = None
    ebay_order_id: Optional[str]
    ebay_item_id: Optional[str]
    sku: Optional[str]
    created_at: str
    message_count: int
    unread_count: int = 0
    is_flagged: bool = False
    last_message_preview: Optional[str] = None

    model_config = {"from_attributes": True}


class ThreadDetail(BaseModel):
    thread_id: str
    buyer_username: Optional[str] = None
    ebay_order_id: Optional[str]
    ebay_item_id: Optional[str]
    sku: Optional[str]
    tracking_number: Optional[str]
    is_flagged: bool = False
    created_at: str
    messages: List[MessageResponse]

    model_config = {"from_attributes": True}


class DraftRequest(BaseModel):
    extra_instructions: Optional[str] = Field(None, max_length=2000)
    procedure: Optional[str] = Field(None, description="Procedure name to apply (e.g., 'proof_of_fault')")


class DraftResponse(BaseModel):
    draft: str


class SendRequest(BaseModel):
    content: str = Field("", max_length=8000)
    draft_content: Optional[str] = Field(None, max_length=8000, description="AI draft they started from; used to record feedback for learning")
    message_media: Optional[List[MessageMediaItem]] = Field(None, description="Attachments: IMAGE, DOC, PDF, TXT. mediaUrl must be HTTPS. Max 5 per message.")


class SendResponse(BaseModel):
    success: bool
    message: str


class FlagRequest(BaseModel):
    is_flagged: bool


class FlagResponse(BaseModel):
    thread_id: str
    is_flagged: bool


# === Endpoints ===

@router.get("/threads", response_model=List[ThreadSummary])
async def list_threads(
    filter: Optional[str] = None,
    search: Optional[str] = None,
    sender_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    List message threads. Uses cached last_message_preview, unread_count, message_count on thread for fast response.
    Optional filter: 'unread', 'flagged', or None (all). Optional search and sender_type.
    """
    from sqlalchemy import or_
    q = select(MessageThread).order_by(
        func.coalesce(MessageThread.last_message_at, MessageThread.created_at).desc()
    )
    if filter == "flagged":
        q = q.where(MessageThread.is_flagged == True)
    elif filter == "unread":
        q = q.where(MessageThread.unread_count > 0)
    if sender_type == "customer":
        q = q.where(MessageThread.buyer_username != "eBay")
    elif sender_type == "ebay":
        q = q.where(MessageThread.buyer_username == "eBay")
    if search and search.strip():
        search_term = f"%{search.strip()}%"
        matching = (
            select(Message.thread_id)
            .where(
                or_(
                    Message.content.ilike(search_term),
                    Message.subject.ilike(search_term),
                    Message.sender_username.ilike(search_term),
                )
            )
            .distinct()
            .subquery()
        )
        q = q.where(MessageThread.thread_id.in_(select(matching.c.thread_id)))
    result = await db.execute(q)
    threads = result.scalars().all()
    # Fallback: threads with null or seller buyer_username get display name from first non-seller message (same as get_thread)
    need_fallback_ids = [
        t.thread_id for t in threads
        if not t.buyer_username or _is_seller_username(t.buyer_username or "")
    ]
    buyer_fallback: dict[str, Optional[str]] = {}
    if need_fallback_ids:
        fallback_result = await db.execute(
            select(Message.thread_id, Message.sender_username)
            .where(
                Message.thread_id.in_(need_fallback_ids),
                Message.sender_type != "seller",
                Message.sender_username.isnot(None),
            )
            .order_by(Message.thread_id, Message.ebay_created_at)
        )
        for row in fallback_result.all():
            tid = getattr(row, "thread_id", None)
            uname = getattr(row, "sender_username", None)
            if tid and uname and not _is_seller_username(uname) and tid not in buyer_fallback:
                buyer_fallback[tid] = uname
    buyer_usernames = {t.buyer_username for t in threads if t.buyer_username and not _is_seller_username(t.buyer_username)}
    for tid, uname in buyer_fallback.items():
        buyer_usernames.add(uname)
    buyer_order_map = {}
    if buyer_usernames:
        order_result = await db.execute(
            select(Order.buyer_username, Order.ebay_order_id)
            .where(Order.buyer_username.in_(buyer_usernames))
            .order_by(Order.date.desc())
        )
        for row in order_result.all():
            if row.buyer_username not in buyer_order_map:
                buyer_order_map[row.buyer_username] = row.ebay_order_id

    def _list_buyer_display(t: MessageThread) -> Optional[str]:
        raw = t.buyer_username if not _is_seller_username(t.buyer_username or "") else None
        if raw:
            return raw
        return buyer_fallback.get(t.thread_id)

    return [
        ThreadSummary(
            thread_id=t.thread_id,
            buyer_username=_list_buyer_display(t),
            ebay_order_id=t.ebay_order_id or buyer_order_map.get(_list_buyer_display(t) or ""),
            ebay_item_id=t.ebay_item_id,
            sku=t.sku,
            created_at=t.created_at.isoformat(),
            unread_count=t.unread_count or 0,
            is_flagged=t.is_flagged,
            message_count=t.message_count or 0,
            last_message_preview=t.last_message_preview,
        )
        for t in threads
    ]


@router.get("/threads/{thread_id}", response_model=ThreadDetail)
async def get_thread(thread_id: str, db: AsyncSession = Depends(get_db)):
    """Get a thread with all messages."""
    result = await db.execute(
        select(MessageThread)
        .where(MessageThread.thread_id == thread_id)
        .options(selectinload(MessageThread.messages))
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    msgs = sorted(thread.messages, key=lambda m: m.ebay_created_at)
    # Title = buyer (the person evamp talks to), never the seller. Find first non-seller username.
    buyer_display = thread.buyer_username
    if not buyer_display or _is_seller_username(buyer_display):
        buyer_display = next(
            (m.sender_username for m in thread.messages if m.sender_username and not _is_seller_username(m.sender_username)),
            None
        )
    # Link order by buyer_username if not already set on thread
    ebay_order_id = thread.ebay_order_id
    if not ebay_order_id and buyer_display:
        ebay_order_id = await _find_order_for_buyer(db, buyer_display)
    return ThreadDetail(
        thread_id=thread.thread_id,
        buyer_username=buyer_display,
        ebay_order_id=ebay_order_id,
        ebay_item_id=thread.ebay_item_id,
        sku=thread.sku,
        tracking_number=thread.tracking_number,
        is_flagged=thread.is_flagged,
        created_at=thread.created_at.isoformat(),
        messages=[
            MessageResponse(
                message_id=m.message_id,
                thread_id=m.thread_id,
                sender_type=m.sender_type,
                sender_username=m.sender_username,
                subject=m.subject,
                content=m.content,
                media=[MessageMediaItem(**x) for x in (m.media or [])] or None,
                is_read=m.is_read,
                detected_language=m.detected_language,
                translated_content=m.translated_content,
                ebay_created_at=m.ebay_created_at.isoformat(),
                created_at=m.created_at.isoformat(),
            )
            for m in msgs
        ],
    )


@router.post("/threads/{thread_id}/mark-read", status_code=status.HTTP_204_NO_CONTENT)
async def mark_thread_read(thread_id: str, db: AsyncSession = Depends(get_db)):
    """
    Mark a thread as read on eBay and in the local DB.
    Call this when the user opens/views a thread so read status stays in sync.
    """
    result = await db.execute(
        select(MessageThread)
        .where(MessageThread.thread_id == thread_id)
        .options(selectinload(MessageThread.messages))
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    try:
        access_token = await get_ebay_access_token(db)
        await update_conversation_read(access_token, thread_id, read=True, conversation_type="FROM_MEMBERS")
    except Exception as e:
        logger.warning("mark_thread_read: eBay update failed for %s: %s", thread_id, e)
    for m in thread.messages:
        m.is_read = True
    thread.unread_count = 0
    await db.commit()


@router.post("/threads/{thread_id}/draft", response_model=DraftResponse)
async def draft_reply(
    thread_id: str,
    body: DraftRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate an AI draft reply for the thread. Uses style profile and procedures if available."""
    ai = AIService(db)
    result = await db.execute(
        select(MessageThread)
        .where(MessageThread.thread_id == thread_id)
        .options(selectinload(MessageThread.messages))
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    msgs = sorted(thread.messages, key=lambda m: m.ebay_created_at)
    thread_history = [
        {"role": m.sender_type, "content": (m.subject or "") + "\n" + (m.content or "")}
        for m in msgs
    ]
    
    # Load AI instructions (global + SKU if any)
    global_result = await db.execute(
        select(AIInstruction).where(AIInstruction.type == "global")
    )
    global_instructions = " ".join(
        i.instructions for i in global_result.scalars().all() if i.instructions
    )
    sku_instructions = ""
    if thread.sku:
        sku_result = await db.execute(
            select(AIInstruction).where(
                AIInstruction.type == "sku",
                AIInstruction.sku_code == thread.sku,
            )
        )
        sku_row = sku_result.scalar_one_or_none()
        if sku_row and sku_row.instructions:
            sku_instructions = sku_row.instructions
    
    # Load approved style profile
    style_profile_text = ""
    style_result = await db.execute(
        select(StyleProfile)
        .where(StyleProfile.is_approved == True)
        .order_by(StyleProfile.created_at.desc())
        .limit(1)
    )
    style_profile = style_result.scalar_one_or_none()
    if style_profile and style_profile.style_summary:
        style_profile_text = f"""
COMMUNICATION STYLE (mimic this exactly):
{style_profile.style_summary}

Greeting style: {style_profile.greeting_patterns or 'Use appropriate greeting'}
Closing style: {style_profile.closing_patterns or 'Use appropriate sign-off'}
Tone: {style_profile.tone_description or 'Professional and friendly'}
"""
    
    # Load procedure if specified
    procedure_text = ""
    if body.procedure:
        proc_result = await db.execute(
            select(Procedure).where(Procedure.name == body.procedure)
        )
        procedure = proc_result.scalar_one_or_none()
        if procedure:
            procedure_text = f"""
PROCEDURE TO FOLLOW ({procedure.display_name}):
{procedure.steps}
"""
    
    # Build the prompt
    prompt = "Draft a reply to this customer message."
    
    if style_profile_text:
        prompt += f"\n\n{style_profile_text}"
    
    if procedure_text:
        prompt += f"\n\n{procedure_text}"
    
    if body.extra_instructions:
        prompt += f"\n\nAdditional instructions: {body.extra_instructions}"
    
    if not style_profile_text:
        prompt += "\n\nBe professional, helpful, and concise."
    
    context = {
        "thread_history": thread_history,
        "global_instructions": global_instructions or "",
        "sku_instructions": sku_instructions,
    }
    try:
        draft = await ai.generate_message(prompt, context)
    except ValueError as e:
        # AI configuration errors (no model, no API key, etc.)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except httpx.HTTPStatusError as e:
        # AI provider API errors (invalid key, rate limit, etc.)
        logger.warning("AI provider error: %s %s", e.response.status_code, e.response.text[:200])
        detail = "AI provider error"
        try:
            body_json = e.response.json()
            detail = body_json.get("error", {}).get("message") or body_json.get("message") or str(e)
        except Exception:
            detail = e.response.text[:200] if e.response.text else str(e)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI provider error: {detail}"
        )
    except Exception as e:
        logger.exception("Draft generation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate draft: {e!s}"
        )
    return DraftResponse(draft=draft)


@router.post("/threads/{thread_id}/send", response_model=SendResponse)
async def send_reply(
    thread_id: str,
    body: SendRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Send a reply in the thread via eBay REST Message API.
    """
    content = body.content.strip()
    if not content and not (body.message_media and len(body.message_media) > 0):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provide message text and/or at least one attachment.",
        )
    if content and len(content) > 2000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Message exceeds 2000 character limit ({len(content)} chars).",
        )
    # Get thread
    result = await db.execute(
        select(MessageThread)
        .where(MessageThread.thread_id == thread_id)
        .options(selectinload(MessageThread.messages))
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    # Get eBay token
    try:
        access_token = await get_ebay_access_token(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Send: token error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get eBay token: {e!s}",
        )
    message_media_payload = None
    if body.message_media:
        message_media_payload = [m.model_dump() for m in body.message_media]
        for m in message_media_payload:
            if not (m.get("mediaUrl") or "").strip().startswith("https://"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="All attachment URLs must be HTTPS.",
                )
    message_text = content if content else " "  # eBay requires messageText; use space when only attachments
    try:
        ebay_response = await ebay_send_message(
            access_token,
            conversation_id=thread_id,
            message_text=message_text,
            reference_id=thread.ebay_item_id,
            message_media=message_media_payload,
        )
    except httpx.HTTPStatusError as e:
        detail = ""
        try:
            body_json = e.response.json()
            detail = body_json.get("errors", [{}])[0].get("message") or body_json.get("error_description") or e.response.text
        except Exception:
            detail = e.response.text or str(e)
        logger.warning("eBay send failed: %s %s", e.response.status_code, detail)
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"eBay send failed: {detail}",
        )
    except Exception as e:
        logger.exception("Send: eBay API error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to send message: {e!s}",
        )
    # Store sent message in DB
    ebay_message_id = ebay_response.get("messageId") or f"sent-{datetime.now(timezone.utc).isoformat()}"
    ebay_created = _parse_iso_to_naive_utc(ebay_response.get("createdDate")) or datetime.utcnow()
    seller_username = (settings.EBAY_SELLER_USERNAME or "").strip() or ebay_response.get("senderUserName") or "seller"
    sent_media = _normalize_message_media(ebay_response.get("messageMedia") or [])
    new_msg = Message(
        message_id=ebay_message_id,
        thread_id=thread_id,
        sender_type="seller",
        sender_username=seller_username,
        subject=None,
        content=content if content else "(attachment)",
        media=sent_media if sent_media else None,
        is_read=True,
        ebay_created_at=ebay_created,
    )
    db.add(new_msg)
    preview = (content[:497] + "…") if len(content) > 500 else content
    thread.last_message_preview = preview
    thread.last_message_at = ebay_created
    thread.message_count = (thread.message_count or 0) + 1

    # Record draft feedback for auto-learning (draft vs final)
    if body.draft_content is not None and body.draft_content.strip():
        draft_text = body.draft_content.strip()
        was_edited = content != draft_text
        buyer_summary = None
        for m in sorted(thread.messages, key=lambda x: x.ebay_created_at, reverse=True):
            if m.sender_type != "seller" and (m.content or "").strip():
                buyer_summary = (m.content or "").strip()[:500]
                break
        feedback = DraftFeedback(
            thread_id=thread_id,
            ai_draft=draft_text,
            final_message=content,
            was_edited=was_edited,
            buyer_message_summary=buyer_summary,
        )
        db.add(feedback)

    await db.commit()
    return SendResponse(success=True, message=f"Message sent. ID: {ebay_message_id}")


@router.post("/upload-media", response_model=MessageMediaItem)
async def upload_message_media(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload an image for use as a message attachment. Uses eBay Commerce Media API (requires sell.inventory scope).
    Supported types: JPG, GIF, PNG, BMP, TIFF, AVIF, HEIC, WEBP. Max 5 attachments per message.
    """
    ext = (Path(file.filename or "").suffix or "").lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_IMAGE_EXTENSIONS))}",
        )
    try:
        access_token = await get_ebay_access_token(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Upload: token error")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Token error: {e!s}")
    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to read file: {e!s}")
    try:
        result = await ebay_upload_image(access_token, content, file.filename or f"image{ext}")
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Image upload requires eBay sell.inventory scope. Add it in eBay Developer Portal and re-authorize the app.",
            ) from e
        detail = (e.response.json().get("errors", [{}])[0].get("message")) if e.response.headers.get("content-type", "").startswith("application/json") else e.response.text
        raise HTTPException(status_code=e.response.status_code, detail=detail or str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(e)) from e
    return MessageMediaItem(
        mediaName=result["mediaName"],
        mediaType=result["mediaType"],
        mediaUrl=result.get("mediaUrl"),
    )


@router.post("/threads/{thread_id}/refresh", status_code=status.HTTP_204_NO_CONTENT)
async def refresh_thread_messages(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Refetch messages for a single conversation from eBay and upsert. Use after send instead of a full sync.
    """
    thread = await db.get(MessageThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    try:
        access_token = await get_ebay_access_token(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Refresh thread: token error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get eBay token: {e!s}",
        )
    try:
        msgs = await fetch_all_conversation_messages(
            access_token, thread_id, conversation_type="FROM_MEMBERS"
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 403:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="eBay denied access to messages.",
            ) from e
        raise
    page_msg_ids = [m.get("messageId") for m in msgs if m.get("messageId")]
    existing_by_id = {}
    if page_msg_ids:
        existing_result = await db.execute(select(Message).where(Message.message_id.in_(page_msg_ids)))
        for msg_row in existing_result.scalars().all():
            existing_by_id[msg_row.message_id] = msg_row
    seller_username = (settings.EBAY_SELLER_USERNAME or "").strip().lower()
    for m in msgs:
        msg_id = m.get("messageId")
        if not msg_id:
            continue
        existing = existing_by_id.get(msg_id)
        if existing:
            existing.is_read = bool(m.get("readStatus", False))
            media_list = _normalize_message_media(m.get("messageMedia") or [])
            existing.media = media_list if media_list else None
            continue
        body = m.get("messageBody") or ""
        media = m.get("messageMedia") or []
        media_list = _normalize_message_media(media)
        if media:
            attachment_strs = []
            for i, x in enumerate(media):
                if isinstance(x, dict):
                    name = x.get("mediaName") or x.get("name") or f"file_{i+1}"
                    mtype = x.get("mediaType") or x.get("type") or "FILE"
                    attachment_strs.append(f"[{mtype}: {name}]")
                else:
                    attachment_strs.append(f"[Attachment {i+1}]")
            if attachment_strs:
                body = body + "\n" + " ".join(attachment_strs) if body else " ".join(attachment_strs)
        sender = (m.get("senderUsername") or "").strip()
        sender_type = "seller" if seller_username and sender.lower() == seller_username else "buyer"
        ebay_created = _parse_iso_to_naive_utc(m.get("createdDate")) or datetime.utcnow()
        new_msg = Message(
            message_id=msg_id,
            thread_id=thread_id,
            sender_type=sender_type,
            sender_username=sender or None,
            subject=(m.get("subject") or "").strip() or None,
            content=body,
            media=media_list if media_list else None,
            is_read=bool(m.get("readStatus", False)),
            ebay_created_at=ebay_created,
        )
        db.add(new_msg)
    if msgs:
        last_msg = max(msgs, key=lambda m: m.get("createdDate") or "")
        thread.last_message_at = _parse_iso_to_naive_utc(last_msg.get("createdDate"))
        body_preview = (last_msg.get("messageBody") or "").strip()
        thread.last_message_preview = (body_preview[:500] + "…") if len(body_preview) > 500 else (body_preview or None)
        thread.message_count = len(msgs)
        thread.unread_count = sum(1 for m in msgs if not m.get("readStatus", False))
    await db.commit()


@router.patch("/threads/{thread_id}/flag", response_model=FlagResponse)
async def toggle_thread_flag(
    thread_id: str,
    body: FlagRequest,
    db: AsyncSession = Depends(get_db),
):
    """Toggle the flagged status of a thread."""
    thread = await db.get(MessageThread, thread_id)
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    thread.is_flagged = body.is_flagged
    await db.commit()
    return FlagResponse(thread_id=thread_id, is_flagged=thread.is_flagged)


@router.get("/flagged-count")
async def get_flagged_count(db: AsyncSession = Depends(get_db)):
    """Get the total count of flagged threads."""
    from sqlalchemy import func
    result = await db.execute(
        select(func.count(MessageThread.thread_id)).where(MessageThread.is_flagged == True)
    )
    count = result.scalar() or 0
    return {"flagged_count": count}


# === Translation Endpoints (CS07, CS08) ===

class DetectLanguageRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=5000)


class DetectLanguageResponse(BaseModel):
    language_code: str
    language_name: str


class TranslateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000)
    source_lang: str = Field(..., min_length=2, max_length=5)
    target_lang: str = Field(..., min_length=2, max_length=5)


class TranslateResponse(BaseModel):
    translated: str
    back_translated: str


LANGUAGE_NAMES = {
    "en": "English", "de": "German", "fr": "French", "es": "Spanish",
    "it": "Italian", "pt": "Portuguese", "nl": "Dutch", "pl": "Polish",
    "ru": "Russian", "zh": "Chinese", "ja": "Japanese", "ko": "Korean",
    "ar": "Arabic", "hi": "Hindi", "tr": "Turkish", "sv": "Swedish",
    "da": "Danish", "no": "Norwegian", "fi": "Finnish", "el": "Greek",
    "cs": "Czech", "hu": "Hungarian", "ro": "Romanian", "uk": "Ukrainian",
}


@router.post("/detect-language", response_model=DetectLanguageResponse)
async def detect_language(
    body: DetectLanguageRequest,
    db: AsyncSession = Depends(get_db),
):
    """Detect the language of a text (CS07)."""
    from app.services.ai_service import AIService
    ai = AIService(db)
    try:
        lang_code = await ai.detect_language(body.text)
        lang_name = LANGUAGE_NAMES.get(lang_code, lang_code.upper())
        return DetectLanguageResponse(language_code=lang_code, language_name=lang_name)
    except Exception as e:
        logger.exception("Language detection failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Language detection failed: {e!s}"
        )


@router.post("/translate", response_model=TranslateResponse)
async def translate_text(
    body: TranslateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Translate text with back-translation for verification (CS07, CS08)."""
    from app.services.ai_service import AIService
    ai = AIService(db)
    try:
        result = await ai.translate(body.text, body.source_lang, body.target_lang)
        return TranslateResponse(
            translated=result.get("translated", ""),
            back_translated=result.get("back_translated", ""),
        )
    except Exception as e:
        logger.exception("Translation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Translation failed: {e!s}"
        )


class TranslateThreadResponse(BaseModel):
    translated_count: int
    detected_language: str


@router.post("/threads/{thread_id}/translate-all", response_model=TranslateThreadResponse)
async def translate_thread_messages(
    thread_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Translate all non-English messages in a thread and persist to DB.
    Only translates messages that don't already have translated_content.
    Returns the detected language and count of newly translated messages.
    """
    from app.services.ai_service import AIService
    ai = AIService(db)
    
    result = await db.execute(
        select(MessageThread)
        .where(MessageThread.thread_id == thread_id)
        .options(selectinload(MessageThread.messages))
    )
    thread = result.scalar_one_or_none()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")
    
    detected_lang = "en"
    translated_count = 0
    
    try:
        for msg in thread.messages:
            # Skip very short messages
            if len(msg.content.strip()) < 5:
                continue
            
            # Skip if already translated
            if msg.translated_content:
                # Use existing detected language if available
                if msg.detected_language and msg.detected_language != "en":
                    detected_lang = msg.detected_language
                continue
            
            # Detect language
            lang = await ai.detect_language(msg.content[:500])
            msg.detected_language = lang
            
            if lang != "en":
                detected_lang = lang
                # Translate to English
                result = await ai.translate(msg.content, lang, "en")
                msg.translated_content = result.get("translated", "")
                translated_count += 1
        
        await db.commit()
        
    except Exception as e:
        await db.rollback()
        logger.exception("Thread translation failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Translation failed: {e!s}"
        )
    
    return TranslateThreadResponse(
        translated_count=translated_count,
        detected_language=detected_lang,
    )


import re
from html import unescape as html_unescape


def _strip_html_to_text(html_content: str, max_length: int = 5000) -> str:
    """
    Convert HTML to plain text and truncate to max_length.
    Used for eBay system messages which often contain huge HTML emails.
    """
    if not html_content:
        return ""
    # Remove script and style elements
    text = re.sub(r'<script[^>]*>.*?</script>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    # Replace common block elements with newlines
    text = re.sub(r'<(br|p|div|tr|li|h[1-6])[^>]*>', '\n', text, flags=re.IGNORECASE)
    # Remove all other tags
    text = re.sub(r'<[^>]+>', '', text)
    # Decode HTML entities
    text = html_unescape(text)
    # Normalize whitespace
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = text.strip()
    # Truncate if too long
    if len(text) > max_length:
        text = text[:max_length] + "\n\n[Content truncated...]"
    return text


def _parse_iso_to_naive_utc(iso_str: Optional[str]) -> Optional[datetime]:
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        if dt.tzinfo:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _normalize_message_media(raw: List[Any]) -> List[dict]:
    """Build list of {mediaName, mediaType, mediaUrl} for storage/API. eBay types: IMAGE, DOC, PDF, TXT."""
    out: List[dict] = []
    for i, x in enumerate(raw):
        if not isinstance(x, dict):
            continue
        name = (x.get("mediaName") or x.get("name") or f"file_{i+1}").strip() or f"attachment_{i+1}"
        mtype = (x.get("mediaType") or x.get("type") or "FILE").strip().upper()
        if mtype not in ("IMAGE", "DOC", "PDF", "TXT"):
            mtype = "FILE"
        url = (x.get("mediaUrl") or x.get("mediaURL") or "").strip()
        out.append({"mediaName": name, "mediaType": mtype, "mediaUrl": url or None})
    return out


def _is_seller_username(username: Optional[str]) -> bool:
    """True if this is the seller (evamp) so we must not use it as thread title; title must be the buyer."""
    if not username:
        return False
    u = str(username).strip().lower()
    if settings.EBAY_SELLER_USERNAME and u == settings.EBAY_SELLER_USERNAME.strip().lower():
        return True
    if u.startswith("evamp_"):
        return True
    return False


async def _find_order_for_buyer(db: AsyncSession, buyer_username: Optional[str]) -> Optional[str]:
    """
    Look up the most recent eBay order ID for a buyer username.
    Returns the ebay_order_id if found, else None.
    """
    if not buyer_username:
        return None
    result = await db.execute(
        select(Order.ebay_order_id)
        .where(Order.buyer_username == buyer_username)
        .order_by(Order.date.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    return row


def _buyer_username_from_conversation(conv: dict, seller_username: str) -> Optional[str]:
    """
    Extract the buyer (other party, NOT the seller) from conversation's latestMessage.
    Returns the first username that is not the seller.
    """
    latest = conv.get("latestMessage") or {}
    sender = (latest.get("senderUsername") or "").strip()
    recipient = (latest.get("recipientUsername") or "").strip()
    # Return whichever is NOT the seller
    for name in [sender, recipient]:
        if name and not _is_seller_username(name):
            return name
    # If both are seller (shouldn't happen) or both empty, return None
    return None


class SyncStatusResponse(BaseModel):
    last_sync_at: Optional[str] = None
    is_syncing: bool
    total_unread_count: int


@router.get("/sync-status", response_model=SyncStatusResponse)
async def get_sync_status(db: AsyncSession = Depends(get_db)):
    """Lightweight status for polling: last sync time, whether a sync is running, and total unread count."""
    meta_result = await db.execute(
        select(SyncMetadata).where(SyncMetadata.key == "messages_last_sync_at")
    )
    meta = meta_result.scalar_one_or_none()
    last_sync_at = meta.value if meta and meta.value else None
    unread_result = await db.execute(
        select(func.count(Message.message_id)).where(Message.is_read == False)
    )
    total_unread_count = unread_result.scalar() or 0
    return SyncStatusResponse(
        last_sync_at=last_sync_at,
        is_syncing=_sync_in_progress,
        total_unread_count=total_unread_count,
    )


@router.post("/sync")
async def sync_messages(
    db: AsyncSession = Depends(get_db),
    full: bool = Query(False, description="If true, fetch all member conversations (no start_time filter) to backfill older threads; messages are always retained indefinitely."),
):
    """
    Sync messages from eBay Message API (commerce/message). All synced messages are stored
    in the DB and retained indefinitely (no purge) for warranty and history. Incremental:
    only fetches conversations with activity since last sync unless full=1. Only one sync
    runs at a time; concurrent calls receive 503.
    """
    global _sync_in_progress
    if _sync_lock.locked():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Sync already in progress.",
        )
    async with _sync_lock:
        _sync_in_progress = True
        try:
            return await _do_sync_messages(db, full_sync=full)
        finally:
            _sync_in_progress = False


async def _sync_from_members_full(
    db: AsyncSession,
    access_token: str,
    limit: int,
    seller_username: str,
) -> tuple[int, int]:
    """Run FROM_MEMBERS full sync (no start_time): paginate all conversations, fetch messages, upsert. Returns (threads_added, messages_added). Commits once at end."""
    threads_added = 0
    messages_added = 0
    offset = 0
    while True:
        try:
            conv_page = await fetch_message_conversations_page(
                access_token,
                conversation_type="FROM_MEMBERS",
                start_time=None,
                limit=limit,
                offset=offset,
            )
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 403:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="eBay denied access to messages. Reconnect eBay in Settings so the app requests the message scope (commerce.message).",
                ) from e
            raise
        conversations = conv_page.get("conversations") or []
        if not conversations:
            break
        sem = asyncio.Semaphore(10)

        async def fetch_messages_full(cid: str):
            async with sem:
                return await fetch_all_conversation_messages(
                    access_token, cid, conversation_type="FROM_MEMBERS"
                )

        conv_ids = [c.get("conversationId") for c in conversations if c.get("conversationId")]
        msg_results = await asyncio.gather(
            *[fetch_messages_full(cid) for cid in conv_ids],
            return_exceptions=True,
        )
        id_to_msgs = dict(zip(conv_ids, msg_results))
        page_msg_ids = []
        for cid in conv_ids:
            msgs_result = id_to_msgs.get(cid)
            if isinstance(msgs_result, BaseException):
                continue
            for m in msgs_result or []:
                mid = m.get("messageId")
                if mid:
                    page_msg_ids.append(mid)
        existing_by_id = {}
        if page_msg_ids:
            existing_result = await db.execute(select(Message).where(Message.message_id.in_(page_msg_ids)))
            for msg_row in existing_result.scalars().all():
                existing_by_id[msg_row.message_id] = msg_row
        for conv in conversations:
            conversation_id = conv.get("conversationId")
            if not conversation_id:
                continue
            msgs_result = id_to_msgs.get(conversation_id)
            if isinstance(msgs_result, BaseException):
                logger.warning("Messages fetch failed for %s: %s", conversation_id, msgs_result)
                continue
            msgs = msgs_result
            ref_id = conv.get("referenceId")
            ref_type = conv.get("referenceType")
            created_date = _parse_iso_to_naive_utc(conv.get("createdDate"))
            buyer_name = _buyer_username_from_conversation(conv, seller_username)
            if _is_seller_username(buyer_name):
                buyer_name = None
            thread = await db.get(MessageThread, conversation_id)
            if not thread:
                thread = MessageThread(
                    thread_id=conversation_id,
                    buyer_username=buyer_name,
                    ebay_item_id=ref_id if ref_type == "LISTING" else None,
                    ebay_order_id=None,
                    sku=None,
                    created_at=created_date or datetime.utcnow(),
                )
                db.add(thread)
                await db.flush()
                threads_added += 1
            else:
                if not thread.buyer_username and buyer_name:
                    thread.buyer_username = buyer_name
            for m in msgs:
                msg_id = m.get("messageId")
                if not msg_id:
                    continue
                existing = existing_by_id.get(msg_id)
                if existing:
                    existing.is_read = bool(m.get("readStatus", False))
                    media_list = _normalize_message_media(m.get("messageMedia") or [])
                    existing.media = media_list if media_list else None
                    continue
                body = m.get("messageBody") or ""
                media = m.get("messageMedia") or []
                media_list = _normalize_message_media(media)
                if media:
                    attachment_strs = []
                    for i, x in enumerate(media):
                        if isinstance(x, dict):
                            name = x.get("mediaName") or x.get("name") or f"file_{i+1}"
                            mtype = x.get("mediaType") or x.get("type") or "FILE"
                            attachment_strs.append(f"[{mtype}: {name}]")
                        else:
                            attachment_strs.append(f"[Attachment {i+1}]")
                    if attachment_strs:
                        body = body + "\n" + " ".join(attachment_strs) if body else " ".join(attachment_strs)
                sender = (m.get("senderUsername") or "").strip()
                sender_type = "seller" if seller_username and sender.lower() == seller_username else "buyer"
                ebay_created = _parse_iso_to_naive_utc(m.get("createdDate")) or datetime.utcnow()
                new_msg = Message(
                    message_id=msg_id,
                    thread_id=conversation_id,
                    sender_type=sender_type,
                    sender_username=sender or None,
                    subject=(m.get("subject") or "").strip() or None,
                    content=body,
                    media=media_list if media_list else None,
                    is_read=bool(m.get("readStatus", False)),
                    ebay_created_at=ebay_created,
                )
                db.add(new_msg)
                messages_added += 1
            if msgs:
                last_msg = max(msgs, key=lambda m: m.get("createdDate") or "")
                thread.last_message_at = _parse_iso_to_naive_utc(last_msg.get("createdDate"))
                body_preview = (last_msg.get("messageBody") or "").strip()
                thread.last_message_preview = (body_preview[:500] + "…") if len(body_preview) > 500 else (body_preview or None)
                thread.message_count = len(msgs)
                thread.unread_count = sum(1 for m in msgs if not m.get("readStatus", False))
        total = conv_page.get("total") or 0
        offset += limit
        if offset >= total or not conv_page.get("next"):
            break
    await db.commit()
    return (threads_added, messages_added)


async def _do_sync_messages(db: AsyncSession, full_sync: bool = False):
    """Inner sync logic; called with _sync_lock held. Messages are never purged; only stub-* threads are removed."""
    logger.info("=" * 80)
    logger.info("Messages sync: start (full_sync=%s)", full_sync)
    logger.info("=" * 80)
    from sqlalchemy import delete

    try:
        await db.execute(delete(Message).where(Message.thread_id.like("stub-%")))
        await db.execute(delete(MessageThread).where(MessageThread.thread_id.like("stub-%")))
        await db.commit()
    except Exception as e:
        await db.rollback()
        logger.exception("Messages sync: DB error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error: {e!s}. Run migrations.",
        )

    try:
        access_token = await get_ebay_access_token(db)
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Messages sync: token error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get eBay token: {e!s}",
        )

    seller_username = (settings.EBAY_SELLER_USERNAME or "").strip().lower()
    sync_start_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

    threads_synced = 0
    messages_synced = 0
    limit = 50
    sync_summary: dict[str, Any] = {"full_sync": full_sync}
    ran_full_sync = full_sync
    need_periodic_full = False
    try:
        if not full_sync:
            full_meta_result = await db.execute(
                select(SyncMetadata).where(SyncMetadata.key == "messages_last_full_sync_at")
            )
            full_meta = full_meta_result.scalar_one_or_none()
            last_full_at: Optional[datetime] = None
            if full_meta and full_meta.value:
                try:
                    last_full_at = datetime.fromisoformat(full_meta.value.replace("Z", "+00:00"))
                except ValueError:
                    pass
            need_periodic_full = last_full_at is None or (datetime.now(timezone.utc) - last_full_at) > timedelta(minutes=10)
            if need_periodic_full:
                logger.info("Messages sync: periodic full due (last full > 10 min), will run after incremental")

        if full_sync:
            logger.info("Messages sync: full_sync=True, FROM_MEMBERS only (no start_time)")
            t, m = await _sync_from_members_full(db, access_token, limit, seller_username)
            threads_synced += t
            messages_synced += m
        else:
            # Incremental: start_time from last sync; FROM_MEMBERS only (eBay getConversations supports only FROM_MEMBERS and FROM_EBAY).
            # With start_time, eBay returns only conversations with buyer activity since that time; seller-only replies are not included.
            member_sync_result = await db.execute(
                select(SyncMetadata).where(SyncMetadata.key == "messages_member_last_sync_at")
            )
            member_sync_meta = member_sync_result.scalar_one_or_none()
            start_time = member_sync_meta.value if (member_sync_meta and member_sync_meta.value) else None
            logger.info("Messages sync: incremental start_time=%r", start_time)

            if not start_time:
                logger.info("Messages sync: incremental but no start_time (first run), doing full FROM_MEMBERS to establish baseline")
                member_convs = await fetch_all_conversations(
                    access_token, "FROM_MEMBERS", start_time=None, limit=limit
                )
                logger.info("Incremental first-run: fetched %d FROM_MEMBERS conversations", len(member_convs))
            else:
                member_convs = await fetch_all_conversations(
                    access_token, "FROM_MEMBERS", start_time=start_time, limit=limit
                )
                logger.info("Incremental: FROM_MEMBERS returned %d conversations since start_time", len(member_convs))

            all_convs = {c.get("conversationId"): c for c in member_convs if c.get("conversationId")}
            fetch_list: List[tuple[str, str]] = [(cid, "FROM_MEMBERS") for cid in all_convs]
            sync_summary["start_time"] = start_time or "(none)"
            sync_summary["from_members"] = len(member_convs)
            sync_summary["fetch_list"] = len(fetch_list)
            if not fetch_list:
                logger.info("Incremental: 0 conversations with activity since start_time")
                logger.info("Incremental summary: start_time=%s, FROM_MEMBERS=%d, fetch_list=0", start_time or "(none)", len(member_convs))
                await db.commit()
            else:
                sem = asyncio.Semaphore(10)

                async def fetch_messages_for_cid_type(item: tuple[str, str]):
                    cid, ctype = item
                    async with sem:
                        return await fetch_all_conversation_messages(
                            access_token, cid, conversation_type=ctype
                        )

                msg_results = await asyncio.gather(
                    *[fetch_messages_for_cid_type(item) for item in fetch_list],
                    return_exceptions=True,
                )
                id_type_to_msgs = dict(zip(fetch_list, msg_results))
                id_to_msgs_merged: dict[str, list] = {}
                for (cid, ctype), result in id_type_to_msgs.items():
                    if isinstance(result, BaseException):
                        logger.warning("Messages fetch failed for %s (%s): %s", cid, ctype, result)
                        continue
                    seen_ids = {m.get("messageId") for m in id_to_msgs_merged.get(cid, [])}
                    for m in result or []:
                        mid = m.get("messageId")
                        if mid and mid not in seen_ids:
                            seen_ids.add(mid)
                            id_to_msgs_merged.setdefault(cid, []).append(m)
                for cid, msgs in id_to_msgs_merged.items():
                    msgs.sort(key=lambda x: x.get("createdDate") or "")

                page_msg_ids = []
                for msgs in id_to_msgs_merged.values():
                    for m in msgs:
                        mid = m.get("messageId")
                        if mid:
                            page_msg_ids.append(mid)
                existing_by_id = {}
                if page_msg_ids:
                    existing_result = await db.execute(select(Message).where(Message.message_id.in_(page_msg_ids)))
                    for msg_row in existing_result.scalars().all():
                        existing_by_id[msg_row.message_id] = msg_row

                for cid, conv in all_convs.items():
                    msgs = id_to_msgs_merged.get(cid, [])
                    ref_id = conv.get("referenceId")
                    ref_type = conv.get("referenceType")
                    created_date = _parse_iso_to_naive_utc(conv.get("createdDate"))
                    buyer_name = _buyer_username_from_conversation(conv, seller_username)
                    if _is_seller_username(buyer_name):
                        buyer_name = None
                    thread = await db.get(MessageThread, cid)
                    if not thread:
                        thread = MessageThread(
                            thread_id=cid,
                            buyer_username=buyer_name,
                            ebay_item_id=ref_id if ref_type == "LISTING" else None,
                            ebay_order_id=None,
                            sku=None,
                            created_at=created_date or datetime.utcnow(),
                        )
                        db.add(thread)
                        await db.flush()
                        threads_synced += 1
                    else:
                        if not thread.buyer_username and buyer_name:
                            thread.buyer_username = buyer_name
                    for m in msgs:
                        msg_id = m.get("messageId")
                        if not msg_id:
                            continue
                        existing = existing_by_id.get(msg_id)
                        if existing:
                            existing.is_read = bool(m.get("readStatus", False))
                            media_list = _normalize_message_media(m.get("messageMedia") or [])
                            existing.media = media_list if media_list else None
                            continue
                        body = m.get("messageBody") or ""
                        media = m.get("messageMedia") or []
                        media_list = _normalize_message_media(media)
                        if media:
                            attachment_strs = []
                            for i, x in enumerate(media):
                                if isinstance(x, dict):
                                    name = x.get("mediaName") or x.get("name") or f"file_{i+1}"
                                    mtype = x.get("mediaType") or x.get("type") or "FILE"
                                    attachment_strs.append(f"[{mtype}: {name}]")
                                else:
                                    attachment_strs.append(f"[Attachment {i+1}]")
                            if attachment_strs:
                                body = body + "\n" + " ".join(attachment_strs) if body else " ".join(attachment_strs)
                        sender = (m.get("senderUsername") or "").strip()
                        sender_type = "seller" if seller_username and sender.lower() == seller_username else "buyer"
                        ebay_created = _parse_iso_to_naive_utc(m.get("createdDate")) or datetime.utcnow()
                        new_msg = Message(
                            message_id=msg_id,
                            thread_id=cid,
                            sender_type=sender_type,
                            sender_username=sender or None,
                            subject=(m.get("subject") or "").strip() or None,
                            content=body,
                            media=media_list if media_list else None,
                            is_read=bool(m.get("readStatus", False)),
                            ebay_created_at=ebay_created,
                        )
                        db.add(new_msg)
                        messages_synced += 1
                    if msgs:
                        last_msg = max(msgs, key=lambda x: x.get("createdDate") or "")
                        thread.last_message_at = _parse_iso_to_naive_utc(last_msg.get("createdDate"))
                        body_preview = (last_msg.get("messageBody") or "").strip()
                        thread.last_message_preview = (body_preview[:500] + "…") if len(body_preview) > 500 else (body_preview or None)
                        thread.message_count = len(msgs)
                        thread.unread_count = sum(1 for x in msgs if not x.get("readStatus", False))
                logger.info(
                    "Incremental summary: start_time=%s, FROM_MEMBERS=%d, fetch_list=%d",
                    start_time or "(none)",
                    len(member_convs),
                    len(fetch_list),
                )
                logger.info(
                    "Incremental done: convs=%d threads_synced=%d messages_synced=%d",
                    len(all_convs),
                    threads_synced,
                    messages_synced,
                )
                await db.commit()

            if need_periodic_full:
                logger.info("Messages sync: running periodic full (FROM_MEMBERS, no start_time)")
                t, m = await _sync_from_members_full(db, access_token, limit, seller_username)
                threads_synced += t
                messages_synced += m
                ran_full_sync = True

        # Sync FROM_EBAY (eBay system messages: returns, cases, promotions)
        # HTML content is stripped to plain text to reduce size
        # Commits after each page so progress is saved even if timeout occurs
        # Tracks offset to enable progressive historical sync across multiple runs
        ebay_threads_synced = 0
        ebay_messages_synced = 0
        
        # Load saved offset for progressive historical sync
        ebay_offset_result = await db.execute(
            select(SyncMetadata).where(SyncMetadata.key == "ebay_messages_offset")
        )
        ebay_offset_meta = ebay_offset_result.scalar_one_or_none()
        offset = int(ebay_offset_meta.value) if ebay_offset_meta else 0
        # Normal sync: 1 page per run so sync finishes quickly; full_sync: more pages to backfill
        max_pages = 5 if full_sync else 1
        pages_fetched = 0
        reached_end = False
        try:
            while pages_fetched < max_pages:
                conv_page = await fetch_message_conversations_page(
                    access_token,
                    conversation_type="FROM_EBAY",
                    limit=limit,
                    offset=offset,
                )
                pages_fetched += 1
                conversations = conv_page.get("conversations") or []
                if not conversations:
                    break
                ebay_sem = asyncio.Semaphore(10)

                async def fetch_ebay_messages(cid: str):
                    async with ebay_sem:
                        return await fetch_all_conversation_messages(
                            access_token, cid, conversation_type="FROM_EBAY"
                        )

                conv_ids = [c.get("conversationId") for c in conversations if c.get("conversationId")]
                ebay_msg_results = await asyncio.gather(
                    *[fetch_ebay_messages(cid) for cid in conv_ids],
                    return_exceptions=True,
                )
                id_to_ebay_msgs = dict(zip(conv_ids, ebay_msg_results))

                # Batch-load existing message IDs for this page
                page_msg_ids = []
                for cid in conv_ids:
                    msgs_result = id_to_ebay_msgs.get(cid)
                    if isinstance(msgs_result, BaseException):
                        continue
                    for m in msgs_result or []:
                        mid = m.get("messageId")
                        if mid:
                            page_msg_ids.append(mid)
                existing_ebay_by_id = {}
                if page_msg_ids:
                    existing_ebay_result = await db.execute(select(Message).where(Message.message_id.in_(page_msg_ids)))
                    for msg_row in existing_ebay_result.scalars().all():
                        existing_ebay_by_id[msg_row.message_id] = msg_row

                page_threads = 0
                page_messages = 0
                for conv in conversations:
                    conversation_id = conv.get("conversationId")
                    if not conversation_id:
                        continue
                    msgs_result = id_to_ebay_msgs.get(conversation_id)
                    if isinstance(msgs_result, BaseException):
                        logger.warning("FROM_EBAY messages fetch failed for %s: %s", conversation_id, msgs_result)
                        continue
                    msgs = msgs_result
                    thread = await db.get(MessageThread, conversation_id)
                    if not thread:
                        ref_id = conv.get("referenceId")
                        ref_type = conv.get("referenceType")
                        created_date = _parse_iso_to_naive_utc(conv.get("createdDate"))
                        thread = MessageThread(
                            thread_id=conversation_id,
                            buyer_username="eBay",
                            ebay_item_id=ref_id if ref_type == "LISTING" else None,
                            ebay_order_id=ref_id if ref_type == "ORDER" else None,
                            sku=None,
                            created_at=created_date or datetime.utcnow(),
                        )
                        db.add(thread)
                        await db.flush()
                        page_threads += 1
                    for m in msgs:
                        msg_id = m.get("messageId")
                        if not msg_id:
                            continue
                        existing = existing_ebay_by_id.get(msg_id)
                        if existing:
                            existing.is_read = bool(m.get("readStatus", False))
                            media_list = _normalize_message_media(m.get("messageMedia") or [])
                            existing.media = media_list if media_list else None
                            continue
                        raw_body = m.get("messageBody") or ""
                        body = _strip_html_to_text(raw_body) if "<" in raw_body else raw_body
                        media = m.get("messageMedia") or []
                        media_list = _normalize_message_media(media)
                        sender = (m.get("senderUsername") or "eBay").strip()
                        subject = (m.get("subject") or "").strip() or None
                        ebay_created = _parse_iso_to_naive_utc(m.get("createdDate")) or datetime.utcnow()
                        new_msg = Message(
                            message_id=msg_id,
                            thread_id=conversation_id,
                            sender_type="ebay",
                            sender_username=sender,
                            subject=subject,
                            content=body,
                            media=media_list if media_list else None,
                            is_read=bool(m.get("readStatus", False)),
                            ebay_created_at=ebay_created,
                        )
                        db.add(new_msg)
                        page_messages += 1
                    if msgs:
                        last_m = max(msgs, key=lambda x: x.get("createdDate") or "")
                        thread.last_message_at = _parse_iso_to_naive_utc(last_m.get("createdDate"))
                        body_preview = (last_m.get("messageBody") or "").strip()
                        thread.last_message_preview = (_strip_html_to_text(body_preview)[:497] + "…") if len(body_preview) > 500 else (_strip_html_to_text(body_preview) if "<" in body_preview else body_preview or None)
                        thread.message_count = len(msgs)
                        thread.unread_count = sum(1 for x in msgs if not x.get("readStatus", False))
                # Commit after each page so progress is saved
                ebay_threads_synced += page_threads
                ebay_messages_synced += page_messages
                logger.info("FROM_EBAY page %d (offset %d): +%d threads, +%d messages", pages_fetched, offset, page_threads, page_messages)
                total = conv_page.get("total") or 0
                offset += limit
                
                # Save offset after each page so progress survives timeout
                if ebay_offset_meta:
                    ebay_offset_meta.value = str(offset)
                else:
                    ebay_offset_meta = SyncMetadata(key="ebay_messages_offset", value=str(offset))
                    db.add(ebay_offset_meta)
                await db.commit()
                
                if offset >= total or not conv_page.get("next"):
                    reached_end = True
                    break
            threads_synced += ebay_threads_synced
            messages_synced += ebay_messages_synced
            
            # Reset offset to 0 if we reached the end (for future incremental syncs)
            if reached_end:
                if ebay_offset_meta:
                    ebay_offset_meta.value = "0"
                    await db.commit()
                logger.info("FROM_EBAY: reached end of historical data, offset reset to 0")
        except httpx.HTTPStatusError as e:
            logger.warning("FROM_EBAY HTTP error %s, partial progress saved", e.response.status_code)
        except Exception as e:
            logger.warning("FROM_EBAY sync error: %s, partial progress saved", e)

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        meta_updates: list[tuple[str, str]] = [
            ("messages_last_sync_at", now_utc),
            ("messages_member_last_sync_at", sync_start_time),
        ]
        if ran_full_sync:
            meta_updates.append(("messages_last_full_sync_at", now_utc))
        for key, value in meta_updates:
            meta_result = await db.execute(select(SyncMetadata).where(SyncMetadata.key == key))
            meta_row = meta_result.scalar_one_or_none()
            if meta_row:
                meta_row.value = value
            else:
                db.add(SyncMetadata(key=key, value=value))
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as e:
        await db.rollback()
        logger.warning("Messages sync: duplicate key (concurrent sync or API overlap): %s", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Sync conflict (duplicate). Please try again.",
        ) from e
    except Exception as e:
        await db.rollback()
        logger.exception("Messages sync: eBay or DB error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {e!s}",
        )

    sync_summary["threads_synced"] = threads_synced
    sync_summary["messages_synced"] = messages_synced
    sync_summary["ebay_threads_synced"] = ebay_threads_synced
    sync_summary["ebay_messages_synced"] = ebay_messages_synced
    if ran_full_sync and not full_sync:
        sync_summary["periodic_full_run"] = True
    sync_summary["at"] = datetime.now(timezone.utc).isoformat()
    try:
        log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        summary_path = log_dir / "sync_summary.log"
        with open(summary_path, "a") as f:
            f.write(json.dumps(sync_summary) + "\n")
    except Exception as e:
        logger.warning("Could not write sync summary log: %s", e)

    logger.info(
        "Messages sync: done full_sync=%s threads_synced=%d messages_synced=%d (FROM_EBAY: +%d threads +%d msgs)",
        full_sync,
        threads_synced,
        messages_synced,
        ebay_threads_synced,
        ebay_messages_synced,
    )
    if threads_synced or messages_synced:
        msg = f"Synced {threads_synced} thread(s), {messages_synced} message(s)."
    else:
        msg = "No new conversations or messages to sync."
    return {
        "message": msg,
        "synced": messages_synced,
        "threads_synced": threads_synced,
        "ebay_threads_synced": ebay_threads_synced,
        "ebay_messages_synced": ebay_messages_synced,
    }


# === AI Instructions CRUD (CS06) ===

class AIInstructionCreate(BaseModel):
    type: str = Field(..., pattern="^(global|sku)$", description="global or sku")
    sku_code: Optional[str] = Field(None, max_length=100)
    item_details: Optional[str] = None
    instructions: str = Field(..., min_length=1)


class AIInstructionUpdate(BaseModel):
    item_details: Optional[str] = None
    instructions: Optional[str] = Field(None, min_length=1)


class AIInstructionResponse(BaseModel):
    id: int
    type: str
    sku_code: Optional[str]
    item_details: Optional[str]
    instructions: str
    created_at: str
    updated_at: str

    model_config = {"from_attributes": True}


@router.get("/ai-instructions", response_model=List[AIInstructionResponse])
async def list_ai_instructions(
    type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """List all AI instructions, optionally filtered by type (global/sku)."""
    query = select(AIInstruction).order_by(AIInstruction.type, AIInstruction.sku_code)
    if type:
        query = query.where(AIInstruction.type == type)
    result = await db.execute(query)
    rows = result.scalars().all()
    return [
        AIInstructionResponse(
            id=r.id,
            type=r.type,
            sku_code=r.sku_code,
            item_details=r.item_details,
            instructions=r.instructions,
            created_at=r.created_at.isoformat() if r.created_at else "",
            updated_at=r.updated_at.isoformat() if r.updated_at else "",
        )
        for r in rows
    ]


@router.post("/ai-instructions", response_model=AIInstructionResponse, status_code=status.HTTP_201_CREATED)
async def create_ai_instruction(
    body: AIInstructionCreate,
    db: AsyncSession = Depends(get_db),
):
    """Create a new AI instruction (global or SKU-specific)."""
    # Validate: global instructions must not have sku_code
    if body.type == "global" and body.sku_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Global instructions must not have a sku_code",
        )
    # Validate: SKU instructions must have sku_code
    if body.type == "sku" and not body.sku_code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SKU instructions must have a sku_code",
        )
    # Check for duplicates
    if body.type == "global":
        existing = await db.execute(
            select(AIInstruction).where(AIInstruction.type == "global")
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Global instructions already exist. Update or delete the existing one.",
            )
    else:
        existing = await db.execute(
            select(AIInstruction).where(
                AIInstruction.type == "sku",
                AIInstruction.sku_code == body.sku_code,
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Instructions for SKU '{body.sku_code}' already exist. Update or delete the existing one.",
            )
    
    instruction = AIInstruction(
        type=body.type,
        sku_code=body.sku_code if body.type == "sku" else None,
        item_details=body.item_details,
        instructions=body.instructions,
    )
    db.add(instruction)
    await db.commit()
    await db.refresh(instruction)
    return AIInstructionResponse(
        id=instruction.id,
        type=instruction.type,
        sku_code=instruction.sku_code,
        item_details=instruction.item_details,
        instructions=instruction.instructions,
        created_at=instruction.created_at.isoformat() if instruction.created_at else "",
        updated_at=instruction.updated_at.isoformat() if instruction.updated_at else "",
    )


@router.get("/ai-instructions/{instruction_id}", response_model=AIInstructionResponse)
async def get_ai_instruction(
    instruction_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Get a specific AI instruction by ID."""
    instruction = await db.get(AIInstruction, instruction_id)
    if not instruction:
        raise HTTPException(status_code=404, detail="AI instruction not found")
    return AIInstructionResponse(
        id=instruction.id,
        type=instruction.type,
        sku_code=instruction.sku_code,
        item_details=instruction.item_details,
        instructions=instruction.instructions,
        created_at=instruction.created_at.isoformat() if instruction.created_at else "",
        updated_at=instruction.updated_at.isoformat() if instruction.updated_at else "",
    )


@router.put("/ai-instructions/{instruction_id}", response_model=AIInstructionResponse)
async def update_ai_instruction(
    instruction_id: int,
    body: AIInstructionUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing AI instruction."""
    instruction = await db.get(AIInstruction, instruction_id)
    if not instruction:
        raise HTTPException(status_code=404, detail="AI instruction not found")
    
    if body.item_details is not None:
        instruction.item_details = body.item_details
    if body.instructions is not None:
        instruction.instructions = body.instructions
    
    await db.commit()
    await db.refresh(instruction)
    return AIInstructionResponse(
        id=instruction.id,
        type=instruction.type,
        sku_code=instruction.sku_code,
        item_details=instruction.item_details,
        instructions=instruction.instructions,
        created_at=instruction.created_at.isoformat() if instruction.created_at else "",
        updated_at=instruction.updated_at.isoformat() if instruction.updated_at else "",
    )


@router.delete("/ai-instructions/{instruction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ai_instruction(
    instruction_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an AI instruction."""
    instruction = await db.get(AIInstruction, instruction_id)
    if not instruction:
        raise HTTPException(status_code=404, detail="AI instruction not found")
    await db.delete(instruction)
    await db.commit()


class GenerateGlobalInstructionResponse(BaseModel):
    success: bool
    message: str
    instructions: Optional[str] = None


@router.post("/generate-global-instruction", response_model=GenerateGlobalInstructionResponse)
async def generate_global_instruction_from_history_endpoint(
    db: AsyncSession = Depends(get_db),
):
    """
    Generate the global AI instruction from your message history (seller messages
    from up to 100 threads, plus draft feedback). Creates or updates the global
    instruction. Result appears in Settings > AI Instructions.
    """
    from app.services.global_instruction_from_history import generate_global_instruction_from_history
    out = await generate_global_instruction_from_history(db)
    if not out["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=out["message"],
        )
    return GenerateGlobalInstructionResponse(
        success=True,
        message=out["message"],
        instructions=out.get("instructions"),
    )


# === AI Learning: Style & Procedures ===

class StyleProfileResponse(BaseModel):
    id: int
    greeting_patterns: Optional[str]
    closing_patterns: Optional[str]
    tone_description: Optional[str]
    empathy_patterns: Optional[str]
    solution_approach: Optional[str]
    common_phrases: Optional[str]
    response_length: Optional[str]
    style_summary: Optional[str]
    messages_analyzed: int
    is_approved: bool
    created_at: str
    updated_at: str


class ProcedureResponse(BaseModel):
    id: int
    name: str
    display_name: str
    trigger_phrases: Optional[str]
    steps: str
    example_messages: Optional[str]
    is_auto_extracted: bool
    is_approved: bool
    created_at: str
    updated_at: str


class AnalyzeResponse(BaseModel):
    success: bool
    message: str
    style_profile: Optional[StyleProfileResponse] = None
    procedures: Optional[List[ProcedureResponse]] = None


@router.post("/analyze-style", response_model=AnalyzeResponse)
async def analyze_style(db: AsyncSession = Depends(get_db)):
    """
    Analyze all seller messages and extract communication style.
    AI reads your sent messages and identifies your patterns.
    """
    from sqlalchemy import func
    
    # Fetch seller messages (most recent 200 for analysis)
    result = await db.execute(
        select(Message)
        .where(Message.sender_type == "seller")
        .order_by(Message.ebay_created_at.desc())
        .limit(200)
    )
    seller_messages = result.scalars().all()
    
    if len(seller_messages) < 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Not enough seller messages to analyze. Found {len(seller_messages)}, need at least 10."
        )
    
    # Prepare messages for AI analysis
    messages_text = "\n\n---\n\n".join([
        f"Message {i+1}:\n{msg.content}"
        for i, msg in enumerate(seller_messages[:100])  # Sample 100 for prompt
    ])
    
    ai = AIService(db)
    
    prompt = f"""Analyze these customer service messages and extract the communication style patterns.

MESSAGES TO ANALYZE:
{messages_text}

Extract and provide in this EXACT format (use these exact headings):

GREETING_PATTERNS:
[List the common greeting phrases used, e.g., "Hi", "Hello", "Thank you for your message"]

CLOSING_PATTERNS:
[List the common sign-off phrases used, e.g., "Kind regards", "Best wishes", "Thanks"]

TONE_DESCRIPTION:
[Describe the overall tone: friendly, professional, casual, formal, empathetic, etc.]

EMPATHY_PATTERNS:
[How does this person express understanding and empathy? Quote specific phrases.]

SOLUTION_APPROACH:
[How do they offer solutions? Direct? Options-based? Step-by-step?]

COMMON_PHRASES:
[List frequently used phrases or expressions unique to this person's style]

RESPONSE_LENGTH:
[short/medium/long - typical response length]

STYLE_SUMMARY:
[Write a 2-3 paragraph summary that an AI could use to mimic this communication style. Be specific about word choices, sentence structure, and approach.]
"""

    try:
        response = await ai.generate_message(prompt, {})
    except Exception as e:
        logger.exception("Style analysis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI analysis failed: {e!s}"
        )
    
    # Parse the response
    def extract_section(text: str, section: str) -> str:
        import re
        pattern = rf"{section}:\s*\n(.*?)(?=\n[A-Z_]+:|$)"
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        return match.group(1).strip() if match else ""
    
    greeting = extract_section(response, "GREETING_PATTERNS")
    closing = extract_section(response, "CLOSING_PATTERNS")
    tone = extract_section(response, "TONE_DESCRIPTION")
    empathy = extract_section(response, "EMPATHY_PATTERNS")
    solution = extract_section(response, "SOLUTION_APPROACH")
    phrases = extract_section(response, "COMMON_PHRASES")
    length = extract_section(response, "RESPONSE_LENGTH")
    summary = extract_section(response, "STYLE_SUMMARY")
    
    # Delete old profiles, keep only latest
    await db.execute(select(StyleProfile).where(True))
    old_profiles = await db.execute(select(StyleProfile))
    for old in old_profiles.scalars().all():
        await db.delete(old)
    
    # Create new profile
    profile = StyleProfile(
        greeting_patterns=greeting or None,
        closing_patterns=closing or None,
        tone_description=tone or None,
        empathy_patterns=empathy or None,
        solution_approach=solution or None,
        common_phrases=phrases or None,
        response_length=length[:50] if length else None,
        style_summary=summary or response,  # Fallback to full response
        messages_analyzed=len(seller_messages),
        is_approved=False,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(profile)
    await db.commit()
    await db.refresh(profile)
    
    return AnalyzeResponse(
        success=True,
        message=f"Analyzed {len(seller_messages)} messages. Style profile extracted.",
        style_profile=StyleProfileResponse(
            id=profile.id,
            greeting_patterns=profile.greeting_patterns,
            closing_patterns=profile.closing_patterns,
            tone_description=profile.tone_description,
            empathy_patterns=profile.empathy_patterns,
            solution_approach=profile.solution_approach,
            common_phrases=profile.common_phrases,
            response_length=profile.response_length,
            style_summary=profile.style_summary,
            messages_analyzed=profile.messages_analyzed,
            is_approved=profile.is_approved,
            created_at=profile.created_at.isoformat(),
            updated_at=profile.updated_at.isoformat(),
        )
    )


@router.post("/analyze-procedures", response_model=AnalyzeResponse)
async def analyze_procedures(db: AsyncSession = Depends(get_db)):
    """
    Analyze message threads and extract common procedures/patterns.
    AI identifies situations like "proof of fault", "return requests", etc.
    """
    # Fetch threads with their messages
    result = await db.execute(
        select(MessageThread)
        .options(selectinload(MessageThread.messages))
        .order_by(MessageThread.created_at.desc())
        .limit(50)
    )
    threads = result.scalars().all()
    
    if len(threads) < 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Not enough threads to analyze. Found {len(threads)}, need at least 5."
        )
    
    # Prepare conversations for AI analysis
    conversations = []
    for thread in threads:
        seller_msgs = [m for m in thread.messages if m.sender_type == "seller"]
        buyer_msgs = [m for m in thread.messages if m.sender_type == "buyer"]
        if seller_msgs and buyer_msgs:
            conv = f"Buyer: {buyer_msgs[0].content[:500]}\nSeller: {seller_msgs[0].content[:500]}"
            conversations.append(conv)
    
    conversations_text = "\n\n===\n\n".join(conversations[:30])
    
    ai = AIService(db)
    
    prompt = f"""Analyze these customer service conversations and identify common PROCEDURES that the seller uses.

A procedure is a specific way of handling a type of situation, like:
- Asking for proof of fault (photos/videos of defects)
- Processing return requests
- Handling shipping delays
- Answering product questions
- Resolving complaints

CONVERSATIONS:
{conversations_text}

Identify 3-8 distinct procedures you see. For each, provide in this EXACT format:

PROCEDURE: [short_name_with_underscores]
DISPLAY_NAME: [Human Readable Name]
TRIGGER_PHRASES: [comma-separated phrases that indicate this procedure applies]
STEPS: [Step-by-step what the seller does in this situation]

---

List each procedure separated by "---"
"""

    try:
        response = await ai.generate_message(prompt, {})
    except Exception as e:
        logger.exception("Procedure analysis failed")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"AI analysis failed: {e!s}"
        )
    
    # Parse procedures from response
    import re
    procedure_blocks = re.split(r'\n---\n', response)
    
    extracted_procedures = []
    for block in procedure_blocks:
        name_match = re.search(r'PROCEDURE:\s*(\S+)', block)
        display_match = re.search(r'DISPLAY_NAME:\s*(.+?)(?=\n|$)', block)
        triggers_match = re.search(r'TRIGGER_PHRASES:\s*(.+?)(?=\nSTEPS:|$)', block, re.DOTALL)
        steps_match = re.search(r'STEPS:\s*(.+?)$', block, re.DOTALL)
        
        if name_match and steps_match:
            name = name_match.group(1).strip().lower().replace(" ", "_")[:100]
            display = display_match.group(1).strip() if display_match else name.replace("_", " ").title()
            triggers = triggers_match.group(1).strip() if triggers_match else ""
            steps = steps_match.group(1).strip()
            
            # Check if procedure exists
            existing = await db.execute(
                select(Procedure).where(Procedure.name == name)
            )
            if not existing.scalar_one_or_none():
                proc = Procedure(
                    name=name,
                    display_name=display[:200],
                    trigger_phrases=triggers or None,
                    steps=steps,
                    is_auto_extracted=True,
                    is_approved=False,
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
                db.add(proc)
                extracted_procedures.append(proc)
    
    await db.commit()
    
    # Refresh and build response
    procedure_responses = []
    for proc in extracted_procedures:
        await db.refresh(proc)
        procedure_responses.append(ProcedureResponse(
            id=proc.id,
            name=proc.name,
            display_name=proc.display_name,
            trigger_phrases=proc.trigger_phrases,
            steps=proc.steps,
            example_messages=proc.example_messages,
            is_auto_extracted=proc.is_auto_extracted,
            is_approved=proc.is_approved,
            created_at=proc.created_at.isoformat(),
            updated_at=proc.updated_at.isoformat(),
        ))
    
    return AnalyzeResponse(
        success=True,
        message=f"Analyzed {len(threads)} threads. Found {len(extracted_procedures)} procedures.",
        procedures=procedure_responses,
    )


@router.get("/style-profile", response_model=Optional[StyleProfileResponse])
async def get_style_profile(db: AsyncSession = Depends(get_db)):
    """Get the current style profile (if any)."""
    result = await db.execute(
        select(StyleProfile).order_by(StyleProfile.created_at.desc()).limit(1)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        return None
    return StyleProfileResponse(
        id=profile.id,
        greeting_patterns=profile.greeting_patterns,
        closing_patterns=profile.closing_patterns,
        tone_description=profile.tone_description,
        empathy_patterns=profile.empathy_patterns,
        solution_approach=profile.solution_approach,
        common_phrases=profile.common_phrases,
        response_length=profile.response_length,
        style_summary=profile.style_summary,
        messages_analyzed=profile.messages_analyzed,
        is_approved=profile.is_approved,
        created_at=profile.created_at.isoformat(),
        updated_at=profile.updated_at.isoformat(),
    )


@router.post("/style-profile/approve")
async def approve_style_profile(db: AsyncSession = Depends(get_db)):
    """Approve the current style profile."""
    result = await db.execute(
        select(StyleProfile).order_by(StyleProfile.created_at.desc()).limit(1)
    )
    profile = result.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="No style profile found. Run analysis first.")
    profile.is_approved = True
    await db.commit()
    return {"success": True, "message": "Style profile approved"}


@router.get("/procedures", response_model=List[ProcedureResponse])
async def list_procedures(db: AsyncSession = Depends(get_db)):
    """List all procedures."""
    result = await db.execute(
        select(Procedure).order_by(Procedure.display_name)
    )
    procedures = result.scalars().all()
    return [
        ProcedureResponse(
            id=p.id,
            name=p.name,
            display_name=p.display_name,
            trigger_phrases=p.trigger_phrases,
            steps=p.steps,
            example_messages=p.example_messages,
            is_auto_extracted=p.is_auto_extracted,
            is_approved=p.is_approved,
            created_at=p.created_at.isoformat(),
            updated_at=p.updated_at.isoformat(),
        )
        for p in procedures
    ]


@router.post("/procedures/{procedure_id}/approve")
async def approve_procedure(procedure_id: int, db: AsyncSession = Depends(get_db)):
    """Approve a procedure."""
    proc = await db.get(Procedure, procedure_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    proc.is_approved = True
    await db.commit()
    return {"success": True, "message": f"Procedure '{proc.display_name}' approved"}


@router.delete("/procedures/{procedure_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_procedure(procedure_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a procedure."""
    proc = await db.get(Procedure, procedure_id)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    await db.delete(proc)
    await db.commit()
