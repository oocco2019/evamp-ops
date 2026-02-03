"""
Messages API (Phase 4-6): threads, draft, send.
Send is disabled by default (ENABLE_MESSAGE_SENDING=false); enable when ready to test with real customers.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, Integer
from sqlalchemy.orm import selectinload
from pydantic import BaseModel, Field
import httpx

from app.core.database import get_db
from app.core.config import settings
from app.models.messages import MessageThread, Message, AIInstruction, SyncMetadata
from app.models.stock import Order
from app.services.ai_service import AIService
from app.services.ebay_auth import get_ebay_access_token
from app.services.ebay_client import (
    fetch_message_conversations_page,
    fetch_all_conversation_messages,
    send_message as ebay_send_message,
)

router = APIRouter()
logger = logging.getLogger(__name__)


# === Schemas ===

class MessageResponse(BaseModel):
    message_id: str
    thread_id: str
    sender_type: str
    sender_username: Optional[str]
    subject: Optional[str]
    content: str
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


class DraftResponse(BaseModel):
    draft: str


class SendRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=8000)


class SendResponse(BaseModel):
    success: bool
    message: str


class FlagRequest(BaseModel):
    is_flagged: bool


class FlagResponse(BaseModel):
    thread_id: str
    is_flagged: bool


# === Endpoints ===

@router.get("/sending-enabled")
async def get_sending_enabled():
    """Return whether message sending is enabled. Frontend uses this to enable/disable Send button."""
    return {"sending_enabled": settings.ENABLE_MESSAGE_SENDING}


@router.get("/threads", response_model=List[ThreadSummary])
async def list_threads(
    filter: Optional[str] = None,
    search: Optional[str] = None,
    sender_type: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    """
    List message threads. Optional filter: 'unread', 'flagged', or None (all).
    Optional search: keyword search across content, subject, buyer username.
    Optional sender_type: 'customer' or 'ebay' to filter by message source.
    Sorted by most recent message datetime.
    """
    from sqlalchemy import func, exists, or_
    from sqlalchemy.orm import aliased
    
    # Subquery for last message datetime per thread
    last_msg_subq = (
        select(
            Message.thread_id,
            func.max(Message.ebay_created_at).label("last_message_at"),
            func.count(Message.message_id).label("message_count"),
            func.sum(func.cast(Message.is_read == False, Integer)).label("unread_count"),
        )
        .group_by(Message.thread_id)
        .subquery()
    )
    
    # Main query joining threads with message stats
    q = (
        select(
            MessageThread,
            last_msg_subq.c.last_message_at,
            last_msg_subq.c.message_count,
            last_msg_subq.c.unread_count,
        )
        .outerjoin(last_msg_subq, MessageThread.thread_id == last_msg_subq.c.thread_id)
        .order_by(func.coalesce(last_msg_subq.c.last_message_at, MessageThread.created_at).desc())
    )
    
    if filter == "flagged":
        q = q.where(MessageThread.is_flagged == True)
    elif filter == "unread":
        q = q.where(last_msg_subq.c.unread_count > 0)
    
    # Filter by sender type (customer vs eBay)
    if sender_type == "customer":
        q = q.where(MessageThread.buyer_username != "eBay")
    elif sender_type == "ebay":
        q = q.where(MessageThread.buyer_username == "eBay")
    
    # Search filter - find threads containing matching messages
    if search and search.strip():
        search_term = f"%{search.strip()}%"
        matching_threads_subq = (
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
        q = q.where(MessageThread.thread_id.in_(select(matching_threads_subq.c.thread_id)))
    
    result = await db.execute(q)
    rows = result.all()
    
    # Get thread IDs to fetch last message preview
    thread_ids = [row[0].thread_id for row in rows]
    
    # Fetch last message for each thread (for preview)
    last_messages = {}
    thread_buyer_from_messages = {}  # thread_id -> first non-seller username found
    if thread_ids:
        # Fetch all messages for these threads to find buyer usernames
        msg_result = await db.execute(
            select(Message)
            .where(Message.thread_id.in_(thread_ids))
            .order_by(Message.thread_id, Message.ebay_created_at.desc())
        )
        all_msgs = msg_result.scalars().all()
        for msg in all_msgs:
            # Keep last message per thread (first in desc order)
            if msg.thread_id not in last_messages:
                last_messages[msg.thread_id] = msg
            # Track first non-seller username per thread
            if msg.thread_id not in thread_buyer_from_messages:
                if msg.sender_username and not _is_seller_username(msg.sender_username):
                    thread_buyer_from_messages[msg.thread_id] = msg.sender_username
    
    # Batch lookup for buyer usernames that need order lookup
    buyer_usernames_to_lookup = set()
    for row in rows:
        t = row[0]
        if t.ebay_order_id:
            continue  # Already has order ID
        # Check stored buyer or resolved from messages
        buyer = t.buyer_username
        if not buyer or _is_seller_username(buyer):
            buyer = thread_buyer_from_messages.get(t.thread_id)
        if buyer:
            buyer_usernames_to_lookup.add(buyer)
    
    buyer_order_map = {}
    if buyer_usernames_to_lookup:
        order_result = await db.execute(
            select(Order.buyer_username, Order.ebay_order_id)
            .where(Order.buyer_username.in_(buyer_usernames_to_lookup))
            .order_by(Order.date.desc())
        )
        for order_row in order_result.all():
            if order_row.buyer_username not in buyer_order_map:
                buyer_order_map[order_row.buyer_username] = order_row.ebay_order_id
    
    out = []
    for row in rows:
        t = row[0]
        last_message_at = row[1]
        message_count = row[2] or 0
        unread_count = row[3] or 0
        
        last_msg = last_messages.get(t.thread_id)
        last_preview = None
        if last_msg:
            content = last_msg.content or ""
            last_preview = (content[:80] + "…") if len(content) > 80 else content
        
        # Get buyer username: prefer stored value, fall back to message senders
        buyer_display = t.buyer_username
        if not buyer_display or _is_seller_username(buyer_display):
            # Use buyer found from messages
            buyer_display = thread_buyer_from_messages.get(t.thread_id)
        
        ebay_order_id = t.ebay_order_id or buyer_order_map.get(buyer_display)
        
        out.append(
            ThreadSummary(
                thread_id=t.thread_id,
                buyer_username=buyer_display,
                ebay_order_id=ebay_order_id,
                ebay_item_id=t.ebay_item_id,
                sku=t.sku,
                created_at=t.created_at.isoformat(),
                unread_count=unread_count,
                is_flagged=t.is_flagged,
                message_count=message_count,
                last_message_preview=last_preview,
            )
        )
    return out


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
                is_read=m.is_read,
                detected_language=m.detected_language,
                translated_content=m.translated_content,
                ebay_created_at=m.ebay_created_at.isoformat(),
                created_at=m.created_at.isoformat(),
            )
            for m in msgs
        ],
    )


@router.post("/threads/{thread_id}/draft", response_model=DraftResponse)
async def draft_reply(
    thread_id: str,
    body: DraftRequest,
    db: AsyncSession = Depends(get_db),
):
    """Generate an AI draft reply for the thread. Does not send."""
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
    prompt = "Draft a professional, helpful seller reply to this buyer message."
    if body.extra_instructions:
        prompt += f"\n\nAdditional instructions: {body.extra_instructions}"
    context = {
        "thread_history": thread_history,
        "global_instructions": global_instructions or "Be polite and concise.",
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
    Disabled unless ENABLE_MESSAGE_SENDING=true.
    """
    if not settings.ENABLE_MESSAGE_SENDING:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Message sending is disabled for testing. Set ENABLE_MESSAGE_SENDING=true in .env when you are ready to test replying to real customers.",
        )
    # Validate length
    content = body.content.strip()
    if len(content) > 2000:
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
    # Send via eBay API
    try:
        ebay_response = await ebay_send_message(
            access_token,
            conversation_id=thread_id,
            message_text=content,
            reference_id=thread.ebay_item_id,
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
    new_msg = Message(
        message_id=ebay_message_id,
        thread_id=thread_id,
        sender_type="seller",
        sender_username=seller_username,
        subject=None,
        content=content,
        is_read=True,
        ebay_created_at=ebay_created,
    )
    db.add(new_msg)
    await db.commit()
    return SendResponse(success=True, message=f"Message sent. ID: {ebay_message_id}")


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


@router.post("/sync")
async def sync_messages(db: AsyncSession = Depends(get_db)):
    """
    Sync messages from eBay Message API (commerce/message). Incremental: only fetches
    conversations with activity since last sync when possible, so repeat syncs are fast.
    """
    logger.info("Messages sync: start")
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

    # Incremental: only fetch conversations with activity since last sync (FROM_MEMBERS supports start_time)
    start_time_param: Optional[str] = None
    meta_result = await db.execute(
        select(SyncMetadata).where(SyncMetadata.key == "messages_last_sync_at")
    )
    meta = meta_result.scalar_one_or_none()
    if meta and meta.value:
        try:
            last_dt = datetime.fromisoformat(meta.value.replace("Z", "+00:00"))
            start_time_param = (last_dt - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        except Exception:
            pass

    threads_synced = 0
    messages_synced = 0
    try:
        offset = 0
        limit = 50
        while True:
            try:
                conv_page = await fetch_message_conversations_page(
                    access_token,
                    conversation_type="FROM_MEMBERS",
                    start_time=start_time_param,
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
            for conv in conversations:
                conversation_id = conv.get("conversationId")
                if not conversation_id:
                    continue
                ref_id = conv.get("referenceId")
                ref_type = conv.get("referenceType")
                created_date = _parse_iso_to_naive_utc(conv.get("createdDate"))
                buyer_name = _buyer_username_from_conversation(conv, seller_username)
                if _is_seller_username(buyer_name):
                    buyer_name = None  # Never store seller as thread title; title = buyer only
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
                    threads_synced += 1
                else:
                    if not thread.buyer_username and buyer_name:
                        thread.buyer_username = buyer_name  # buyer_name already cleared if seller
                msgs = await fetch_all_conversation_messages(
                    access_token, conversation_id, conversation_type="FROM_MEMBERS"
                )
                for m in msgs:
                    msg_id = m.get("messageId")
                    if not msg_id:
                        continue
                    existing = await db.get(Message, msg_id)
                    if existing:
                        existing.is_read = bool(m.get("readStatus", False))
                        continue
                    body = m.get("messageBody") or ""
                    media = m.get("messageMedia") or []
                    if media:
                        attachment_strs = []
                        for i, x in enumerate(media):
                            if isinstance(x, dict):
                                name = x.get("mediaName") or x.get("name") or f"file_{i+1}"
                                mtype = x.get("mediaType") or x.get("type") or "FILE"
                                attachment_strs.append(f"[{mtype}: {name}]")
                            else:
                                # Fallback if media item is not a dict (e.g. just a string/ID)
                                attachment_strs.append(f"[Attachment {i+1}]")
                        if attachment_strs:
                            if body:
                                body = body + "\n" + " ".join(attachment_strs)
                            else:
                                body = " ".join(attachment_strs)
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
                        is_read=bool(m.get("readStatus", False)),
                        ebay_created_at=ebay_created,
                    )
                    db.add(new_msg)
                    messages_synced += 1
            total = conv_page.get("total") or 0
            offset += limit
            if offset >= total or not conv_page.get("next"):
                break

        # Commit FROM_MEMBERS progress before starting FROM_EBAY
        await db.commit()

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
        
        max_pages = 5  # Limit pages per sync; run sync multiple times for historical data
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
                page_threads = 0
                page_messages = 0
                for conv in conversations:
                    conversation_id = conv.get("conversationId")
                    if not conversation_id:
                        continue
                    thread = await db.get(MessageThread, conversation_id)
                    is_new_thread = thread is None
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
                    # Only fetch messages for new threads
                    if is_new_thread:
                        msgs = await fetch_all_conversation_messages(
                            access_token, conversation_id, conversation_type="FROM_EBAY"
                        )
                        for m in msgs:
                            msg_id = m.get("messageId")
                            if not msg_id:
                                continue
                            existing = await db.get(Message, msg_id)
                            if existing:
                                continue
                            raw_body = m.get("messageBody") or ""
                            body = _strip_html_to_text(raw_body) if "<" in raw_body else raw_body
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
                                is_read=bool(m.get("readStatus", False)),
                                ebay_created_at=ebay_created,
                            )
                            db.add(new_msg)
                            page_messages += 1
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
                    db.add(SyncMetadata(key="ebay_messages_offset", value=str(offset)))
                    ebay_offset_meta = await db.execute(
                        select(SyncMetadata).where(SyncMetadata.key == "ebay_messages_offset")
                    )
                    ebay_offset_meta = ebay_offset_meta.scalar_one_or_none()
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
        meta_result = await db.execute(
            select(SyncMetadata).where(SyncMetadata.key == "messages_last_sync_at")
        )
        meta_row = meta_result.scalar_one_or_none()
        if meta_row:
            meta_row.value = now_utc
        else:
            db.add(SyncMetadata(key="messages_last_sync_at", value=now_utc))
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        logger.exception("Messages sync: eBay or DB error")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Sync failed: {e!s}",
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
