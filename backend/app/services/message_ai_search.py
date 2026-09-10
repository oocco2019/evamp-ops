"""
AI prompt search over message threads (last N days, full message text).

Batches threads when the corpus is large so each LLM call stays within context.
Returns matching thread_ids only — no per-match rationale.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable, List, Sequence, Tuple

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.messages import MessageThread, Message

logger = logging.getLogger(__name__)

AI_SEARCH_WINDOW_DAYS = 90
# ~350k chars ≈ ~90k tokens — leaves headroom under typical 200k context windows.
MAX_BATCH_CHARS = 350_000
SEARCH_SYSTEM_PROMPT = (
    "You search eBay seller customer-message threads. "
    "Given a natural-language query and a list of threads with full message text, "
    "return ONLY a JSON array of thread_id strings that match the query. "
    "Example: [\"abc123\",\"def456\"]. "
    "If none match, return []. "
    "Do not explain. Do not wrap in markdown."
)


def format_thread_block(thread: MessageThread, messages: Sequence[Message]) -> str:
    """Full-text block for one thread (no truncation of message bodies)."""
    header_parts = [f"thread_id={thread.thread_id}"]
    if thread.buyer_username:
        header_parts.append(f"buyer={thread.buyer_username}")
    if thread.sku:
        header_parts.append(f"sku={thread.sku}")
    if thread.ebay_order_id:
        header_parts.append(f"order={thread.ebay_order_id}")
    if thread.ebay_item_id:
        header_parts.append(f"item={thread.ebay_item_id}")
    lines = [" | ".join(header_parts)]
    for m in messages:
        role = (m.sender_type or "unknown").strip() or "unknown"
        who = (m.sender_username or "").strip()
        prefix = f"[{role}" + (f" {who}" if who else "") + "]"
        subject = (m.subject or "").strip()
        body = (m.content or "").strip()
        if subject:
            lines.append(f"{prefix} subject: {subject}")
        lines.append(f"{prefix} {body}" if body else f"{prefix} (empty)")
    return "\n".join(lines)


def batch_thread_blocks(
    blocks: List[Tuple[str, str]],
    max_chars: int = MAX_BATCH_CHARS,
) -> List[List[Tuple[str, str]]]:
    """
    Pack (thread_id, text) blocks into batches under max_chars.
    A single oversized thread still goes in its own batch (never split mid-thread).
    """
    if max_chars < 1:
        raise ValueError("max_chars must be >= 1")
    batches: List[List[Tuple[str, str]]] = []
    current: List[Tuple[str, str]] = []
    current_len = 0
    sep = 2  # "\n\n" between blocks

    for tid, text in blocks:
        block_len = len(text)
        extra = block_len if not current else sep + block_len
        if current and current_len + extra > max_chars:
            batches.append(current)
            current = []
            current_len = 0
            extra = block_len
        current.append((tid, text))
        current_len += extra
    if current:
        batches.append(current)
    return batches


def parse_matching_thread_ids(raw: str, valid_ids: set[str]) -> List[str]:
    """
    Parse model output into ordered unique thread_ids that appear in valid_ids.
    Accepts a JSON array, or falls back to scanning for known ids in the text.
    """
    text = (raw or "").strip()
    if not text:
        return []

    # Strip common markdown fences
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()

    candidates: List[str] = []
    try:
        # Prefer first [...] JSON array in the response
        start = text.find("[")
        end = text.rfind("]")
        if start != -1 and end != -1 and end > start:
            parsed = json.loads(text[start : end + 1])
            if isinstance(parsed, list):
                for item in parsed:
                    if isinstance(item, str):
                        candidates.append(item.strip())
                    elif isinstance(item, dict) and item.get("thread_id"):
                        candidates.append(str(item["thread_id"]).strip())
    except json.JSONDecodeError:
        candidates = []

    if not candidates:
        # Fallback: any valid id mentioned in the raw text (preserve first-seen order)
        for tid in valid_ids:
            if tid in raw:
                candidates.append(tid)

    seen: set[str] = set()
    out: List[str] = []
    for tid in candidates:
        if tid in valid_ids and tid not in seen:
            seen.add(tid)
            out.append(tid)
    return out


def build_batch_user_prompt(query: str, batch: List[Tuple[str, str]], batch_index: int, batch_total: int) -> str:
    body = "\n\n".join(text for _, text in batch)
    return (
        f"Search query:\n{query.strip()}\n\n"
        f"Threads batch {batch_index}/{batch_total} "
        f"({len(batch)} thread(s)):\n\n"
        f"{body}\n\n"
        "Return a JSON array of matching thread_id values from this batch only."
    )


async def load_recent_thread_blocks(
    db: AsyncSession,
    *,
    window_days: int = AI_SEARCH_WINDOW_DAYS,
) -> List[Tuple[str, str]]:
    """Load threads with activity in the window; return (thread_id, full-text block) newest first."""
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=window_days)
    result = await db.execute(
        select(MessageThread)
        .options(selectinload(MessageThread.messages))
        .where(
            func.coalesce(MessageThread.last_message_at, MessageThread.created_at) >= cutoff,
            ~MessageThread.thread_id.like("stub-%"),
        )
        .order_by(func.coalesce(MessageThread.last_message_at, MessageThread.created_at).desc())
    )
    threads = result.scalars().unique().all()
    blocks: List[Tuple[str, str]] = []
    for t in threads:
        msgs = sorted(t.messages or [], key=lambda m: m.ebay_created_at or m.created_at)
        if not msgs:
            continue
        blocks.append((t.thread_id, format_thread_block(t, msgs)))
    return blocks


CompleteFn = Callable[..., Awaitable[str]]


async def ai_search_thread_ids(
    query: str,
    blocks: List[Tuple[str, str]],
    complete: CompleteFn,
    *,
    max_batch_chars: int = MAX_BATCH_CHARS,
) -> List[str]:
    """
    Run batched LLM search. `complete(user_prompt, system=..., max_tokens=..., temperature=...)`.
    Merges matches across batches; preserves first-seen order (newer threads first within each batch).
    """
    query = (query or "").strip()
    if not query:
        return []
    if not blocks:
        return []

    batches = batch_thread_blocks(blocks, max_chars=max_batch_chars)
    valid = {tid for tid, _ in blocks}
    matched: List[str] = []
    seen: set[str] = set()

    for i, batch in enumerate(batches, start=1):
        user_prompt = build_batch_user_prompt(query, batch, i, len(batches))
        logger.info(
            "message_ai_search: batch %s/%s threads=%s chars=%s",
            i,
            len(batches),
            len(batch),
            sum(len(t) for _, t in batch),
        )
        raw = await complete(
            user_prompt,
            system=SEARCH_SYSTEM_PROMPT,
            max_tokens=4000,
            temperature=0,
        )
        batch_valid = {tid for tid, _ in batch}
        for tid in parse_matching_thread_ids(raw, batch_valid):
            if tid in valid and tid not in seen:
                seen.add(tid)
                matched.append(tid)

    return matched
