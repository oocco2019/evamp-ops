"""
Generate global AI instruction from seller message history (and draft feedback).
Only uses member conversations (buyer/seller chat). Ignores eBay system messages (returns, cases, etc.).
"""
from sqlalchemy import select

from app.core.config import settings
from app.models.messages import MessageThread, Message, AIInstruction, DraftFeedback
from app.services.ai_service import AIService


def _username_looks_like_seller(username: str | None) -> bool:
    """True if this username is the seller (evamp or config)."""
    if not username or not username.strip():
        return False
    u = username.strip().lower()
    if settings.EBAY_SELLER_USERNAME and u == settings.EBAY_SELLER_USERNAME.strip().lower():
        return True
    if u.startswith("evamp_") or u == "evamp" or "evamp" in u:
        return True
    return False


async def generate_global_instruction_from_history(db) -> dict:
    """
    Load seller messages from member conversations only (evamp_ + buyer).
    Ignores eBay system message threads. Collects your (evamp_) messages and extracts patterns.
    Returns dict: { "success": bool, "message": str, "instructions": str | None }
    """
    # Load all threads (member conversations mixed with eBay-only; we filter below)
    thread_result = await db.execute(
        select(MessageThread.thread_id)
        .order_by(MessageThread.updated_at.desc())
    )
    thread_ids = [r[0] for r in thread_result.all()]
    if not thread_ids:
        return {
            "success": False,
            "message": "No threads found.",
            "instructions": None,
        }

    # Load ALL messages for those threads
    msg_result = await db.execute(
        select(Message)
        .where(Message.thread_id.in_(thread_ids))
        .order_by(Message.ebay_created_at)
    )
    all_messages = msg_result.scalars().all()

    # Keep only threads that have at least one buyer or seller message (member conversations)
    member_thread_ids = set()
    for msg in all_messages:
        if msg.sender_type in ("buyer", "seller"):
            member_thread_ids.add(msg.thread_id)

    # In member threads only, take messages that are buyer or seller (exclude ebay)
    member_messages = [
        m for m in all_messages
        if m.thread_id in member_thread_ids and m.sender_type in ("buyer", "seller")
    ]

    # Seller = you (evamp_) or sender_type already 'seller'
    seller_messages = []
    for msg in member_messages:
        content = (msg.content or "").strip()
        if not content:
            continue
        if msg.sender_type == "seller":
            seller_messages.append(content)
            continue
        if _username_looks_like_seller(msg.sender_username):
            seller_messages.append(content)

    if len(seller_messages) < 5:
        return {
            "success": False,
            "message": f"Not enough seller messages in member conversations. Need at least 5; found {len(seller_messages)}. (Skipped {len(thread_ids) - len(member_thread_ids)} eBay-only threads; {len(member_thread_ids)} threads have buyer/seller chat.)",
            "instructions": None,
        }

    sample = seller_messages[:80]
    messages_text = "\n\n---\n\n".join(
        f"Message {i+1}:\n{text}" for i, text in enumerate(sample)
    )

    feedback_result = await db.execute(
        select(DraftFeedback)
        .where(DraftFeedback.was_edited == True)
        .order_by(DraftFeedback.created_at.desc())
        .limit(30)
    )
    feedback_rows = feedback_result.scalars().all()
    feedback_section = ""
    if feedback_rows:
        feedback_lines = []
        for i, row in enumerate(feedback_rows):
            buyer = (row.buyer_message_summary or "?")[:200]
            ai_draft = (row.ai_draft or "")[:400]
            final_msg = (row.final_message or "")[:400]
            feedback_lines.append(
                f"[{i+1}] Buyer asked: {buyer}\nAI draft: {ai_draft}\nSeller actually sent: {final_msg}"
            )
        feedback_section = """
EDIT FEEDBACK (seller edited the AI draft before sending—prefer the seller's version when refining the instruction):
""" + "\n\n".join(feedback_lines) + "\n\n"

    ai = AIService(db)
    prompt = f"""Analyze these customer service messages (from the same seller) and produce a single GLOBAL INSTRUCTION text.

The global instruction will be used by an AI to draft replies in this seller's style and follow their procedures. Output ONLY the instruction text: no headings, no "Instruction:" prefix, no meta-commentary. Write in second person ("When the customer...", "Always...", "Use greetings like...") so it can be pasted directly into a system prompt.

Include:
1. Communication style: tone, typical greetings and sign-offs, response length, empathy, phrasing.
2. Procedures: how they handle returns, defects, proof of fault, shipping issues, complaints—whatever patterns you see.
{feedback_section}
MESSAGES TO ANALYZE:
{messages_text}

Output the global instruction text only (plain text, no markdown):"""

    try:
        instruction_text = await ai.generate_message(prompt, {})
    except Exception as e:
        return {
            "success": False,
            "message": f"AI generation failed: {e!s}",
            "instructions": None,
        }

    instruction_text = (instruction_text or "").strip()
    if not instruction_text:
        return {
            "success": False,
            "message": "AI returned empty instruction.",
            "instructions": None,
        }

    existing = await db.execute(
        select(AIInstruction).where(AIInstruction.type == "global")
    )
    global_instruction = existing.scalar_one_or_none()

    if global_instruction:
        global_instruction.instructions = instruction_text
        await db.commit()
        return {
            "success": True,
            "message": f"Updated global instruction from {len(seller_messages)} seller messages ({len(member_thread_ids)} member threads).",
            "instructions": instruction_text,
        }
    else:
        global_instruction = AIInstruction(
            type="global",
            sku_code=None,
            item_details=None,
            instructions=instruction_text,
        )
        db.add(global_instruction)
        await db.commit()
        return {
            "success": True,
            "message": f"Created global instruction from {len(seller_messages)} seller messages ({len(member_thread_ids)} member threads).",
            "instructions": instruction_text,
        }
