"""
Stage-scoped draft compose for Messages-Test (one LLM call).
"""
from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.models.messages import (
    AIComposition,
    Message,
    MessageThread,
    ReplyStageTemplate,
    SyncMetadata,
)
from app.models.stock import Order
from app.services.reply_compose import resolve_product_context, sanitize_messaging_punctuation, truncate_thread_history
from app.services.reply_router import (
    STYLE_PACK,
    RouterResult,
    build_escalation_card,
    run_router,
)

logger = logging.getLogger(__name__)

META_WHATSAPP = "cs_router_whatsapp"
DEFAULT_WHATSAPP = "+447480850668"


async def _get_whatsapp(db: AsyncSession) -> str:
    meta = await db.get(SyncMetadata, META_WHATSAPP)
    if meta and (meta.value or "").strip():
        return meta.value.strip()
    return DEFAULT_WHATSAPP


async def _stage_instruction(db: AsyncSession, stage: str, whatsapp: str) -> str:
    row = await db.get(ReplyStageTemplate, stage)
    text = (row.instruction if row else "") or (
        "Write one short helpful seller reply for this stage of the conversation."
    )
    return text.replace("{whatsapp}", whatsapp)


def _format_history(thread_history: List[Dict[str, Any]]) -> str:
    if not thread_history:
        return "No previous messages."
    lines = []
    for msg in thread_history:
        role = msg.get("role") or "unknown"
        if role == "buyer":
            who = "Buyer"
        elif role == "seller":
            who = "Seller"
        else:
            who = str(role)
        lines.append(f"[{who}]: {(msg.get('content') or '').strip()}")
    return "\n\n".join(lines)


async def compose_router_draft(
    db: AsyncSession,
    *,
    thread: MessageThread,
    messages: List[Message],
    ebay_order_id: Optional[str],
    extra_instructions: Optional[str],
    ai_generate,
    force_stage: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Returns dict with draft (or None), tier, router, escalation (if tier 3), composition_id.
    """
    t0 = time.perf_counter()
    product = await resolve_product_context(db, thread, ebay_order_id)
    skus = product.get("skus") or ([product["primary_sku"]] if product.get("primary_sku") else [])

    order_date = None
    oid = product.get("order_id")
    if oid:
        result = await db.execute(select(Order).where(Order.ebay_order_id == oid).limit(1))
        order = result.scalar_one_or_none()
        if order and order.date:
            order_date = datetime.combine(order.date, datetime.min.time())

    router = await run_router(
        db,
        thread=thread,
        messages=messages,
        skus=skus,
        order_date=order_date,
        extra_instructions=extra_instructions,
    )
    if force_stage:
        router.stage = force_stage
        router.reasons = list(router.reasons) + [f"force_stage:{force_stage}"]
        if router.tier == 3 and force_stage in {"follow_up", "courier_chase", "safety", "reassurance"}:
            # Allow nudge / safety / reassurance drafts even when otherwise escalated
            router.tier = 2

    if router.tier == 3 and not force_stage:
        card = build_escalation_card(router=router, thread=thread, messages=messages)
        composition = AIComposition(
            thread_id=thread.thread_id,
            sku=product.get("primary_sku"),
            order_id=product.get("order_id"),
            prompt_snapshot={
                "router": router.to_dict(),
                "escalation": card,
                "extra_instructions": (extra_instructions or "").strip() or None,
            },
            policy_ids=[],
            playbook_ids=[],
            model_output="",
            adherence_json={"router": router.to_dict(), "tier": 3},
        )
        db.add(composition)
        await db.flush()
        logger.info(
            "reply_router: tier3 thread=%s intent=%s %.2fs",
            thread.thread_id,
            router.intent,
            time.perf_counter() - t0,
        )
        return {
            "draft": None,
            "tier": 3,
            "router": router.to_dict(),
            "escalation": card,
            "composition_id": composition.id,
        }

    whatsapp = await _get_whatsapp(db)
    stage_text = await _stage_instruction(db, router.stage, whatsapp)

    hist = [
        {"role": m.sender_type, "content": (m.subject or "") + "\n" + (m.content or "")}
        for m in sorted(messages, key=lambda x: x.ebay_created_at or datetime.min)
    ]
    hist = truncate_thread_history(hist, max_messages=8, max_chars=8000)

    system_parts = [STYLE_PACK, "", f"STAGE ({router.stage}):", stage_text]
    if router.known_issue:
        ki = router.known_issue
        system_parts.append("")
        system_parts.append("KNOWN ISSUE MATCH:")
        system_parts.append(f"- id: {ki.get('issue_id')}")
        system_parts.append(f"- diagnosis: {ki.get('diagnosis')}")
        system_parts.append(f"- action: {ki.get('skip_to_action')}")
        if ki.get("disposal_note"):
            system_parts.append("- Tell the buyer they can dispose of the faulty unit (do not return it).")
    product_text = (product.get("product_context_text") or "").strip()
    if product_text:
        system_parts.append("")
        system_parts.append("PRODUCT CONTEXT:")
        system_parts.append(product_text)

    if router.flags.get("seller_greeted_today"):
        system_parts.append("")
        system_parts.append(
            "GREETING RULE (hard): The seller already greeted this buyer earlier today. "
            "Do NOT start with Hi, Hello, Hey, Good morning/afternoon/evening, or similar. "
            "Start directly with the substance of the reply."
        )

    extra = (extra_instructions or "").strip()
    if extra:
        system_parts.append("")
        system_parts.append(
            "ADDITIONAL INSTRUCTIONS FROM SELLER (override the stage if they conflict):"
        )
        system_parts.append(extra)

    system = "\n".join(system_parts)
    user_prompt = (
        "Conversation history:\n\n"
        f"{_format_history(hist)}\n\n"
        "---\n"
        "Draft the seller's next message in English only. No preamble. "
        "Do not write German or any other language — English only."
    )

    max_tokens = int(getattr(app_settings, "REPLY_DRAFT_MAX_TOKENS", 700))
    draft = (
        await ai_generate(
            user_prompt,
            {
                "thread_history": [],
                "policies": [],
                "playbook_entries": [],
                "product_context": "",
                "global_instructions": system,
                "sku_instructions": "",
                "max_tokens": max_tokens,
            },
        )
    ).strip()
    draft = sanitize_messaging_punctuation(draft)

    composition = AIComposition(
        thread_id=thread.thread_id,
        sku=product.get("primary_sku"),
        order_id=product.get("order_id"),
        prompt_snapshot={
            "router": router.to_dict(),
            "stage": router.stage,
            "system": system[:4000],
            "extra_instructions": extra or None,
            "product_context": product_text,
        },
        policy_ids=[],
        playbook_ids=[],
        model_output=draft,
        adherence_json={
            "router": router.to_dict(),
            "tier": router.tier,
            "stage": router.stage,
            "known_issue_id": router.known_issue_id,
        },
    )
    db.add(composition)
    await db.flush()
    logger.info(
        "reply_router: draft thread=%s tier=%s stage=%s %.2fs",
        thread.thread_id,
        router.tier,
        router.stage,
        time.perf_counter() - t0,
    )
    return {
        "draft": draft,
        "tier": router.tier,
        "router": router.to_dict(),
        "escalation": None,
        "composition_id": composition.id,
    }
