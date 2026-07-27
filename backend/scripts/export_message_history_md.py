#!/usr/bin/env python3
"""Export message threads from the last N days to markdown (for handoff / paste into another AI)."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import async_session_maker
from app.models.messages import Message, MessageThread


def esc(s: str) -> str:
    s = (s or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    return s.replace("```", "'''")


async def export(
    out: Path,
    *,
    days: int | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> dict:
    now = datetime.utcnow()
    if since is None:
        if days is None:
            days = 90
        since = now - timedelta(days=days)
    if until is None:
        until = now

    async with async_session_maker() as db:
        q = (
            select(MessageThread)
            .join(Message, Message.thread_id == MessageThread.thread_id)
            .where(
                Message.ebay_created_at >= since,
                Message.ebay_created_at < until,
            )
            .options(selectinload(MessageThread.messages))
            .distinct()
            .order_by(MessageThread.last_message_at.desc().nullslast())
        )
        result = await db.execute(q)
        threads = list(result.scalars().unique().all())

        title_range = f"{since.date().isoformat()} → {until.date().isoformat()}"
        lines: list[str] = [
            f"# EvampOps message history ({title_range})",
            "",
            f"- Exported at (UTC): `{now.isoformat(timespec='seconds')}Z`",
            f"- Window: `{since.date().isoformat()}` ≤ `ebay_created_at` < `{until.date().isoformat()}`",
            "- Messages in window: **PENDING**",
            f"- Threads with activity in window: **{len(threads)}**",
            "",
            "Grouped by thread (chronological within each). Sender labels: Buyer / Seller / eBay / other.",
            "Use this for analysing real multi-turn support style — not for inventing order facts.",
            "",
        ]

        total_msgs = 0
        for i, t in enumerate(threads, 1):
            msgs = sorted(
                (
                    m
                    for m in t.messages
                    if m.ebay_created_at and since <= m.ebay_created_at < until
                ),
                key=lambda m: m.ebay_created_at or datetime.min,
            )
            if not msgs:
                continue
            total_msgs += len(msgs)
            buyer = (t.buyer_username or "Unknown").strip()
            lines.append(f"## Thread {i}: {buyer}")
            lines.append("")
            meta = []
            if t.thread_id:
                meta.append(f"thread_id=`{t.thread_id}`")
            if t.ebay_order_id:
                meta.append(f"order=`{t.ebay_order_id}`")
            if t.sku:
                meta.append(f"sku=`{t.sku}`")
            if t.ebay_item_id:
                meta.append(f"item=`{t.ebay_item_id}`")
            if meta:
                lines.append("- " + " · ".join(meta))
                lines.append("")
            for m in msgs:
                st = (m.sender_type or "").lower()
                if st == "buyer":
                    who = "Buyer"
                elif st == "seller":
                    who = "Seller"
                elif st in ("ebay", "system"):
                    who = "eBay"
                else:
                    who = st or "Unknown"
                uname = (m.sender_username or "").strip()
                when = m.ebay_created_at.isoformat(timespec="minutes") if m.ebay_created_at else "?"
                header = f"### {who}"
                if uname:
                    header += f" (`{uname}`)"
                header += f" — {when}"
                lines.append(header)
                if m.subject:
                    lines.append(f"**Subject:** {esc(m.subject)}")
                    lines.append("")
                body = esc(m.content or "")
                lines.append(body if body else "_(empty)_")
                if m.media:
                    try:
                        n = len(m.media) if isinstance(m.media, list) else 1
                    except Exception:
                        n = 1
                    lines.append("")
                    lines.append(f"_Attachments: {n}_")
                lines.append("")
            lines.append("---")
            lines.append("")

        lines[4] = f"- Messages in window: **{total_msgs}**"
        text = "\n".join(lines)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        return {
            "threads": len(threads),
            "messages": total_msgs,
            "bytes": len(text.encode("utf-8")),
            "path": str(out),
            "since": since.isoformat(),
            "until": until.isoformat(),
        }


def _parse_date(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%d")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=None, help="Rolling last N days ending now (default 90 if no --since)")
    p.add_argument("--since", type=str, default=None, help="Inclusive start YYYY-MM-DD")
    p.add_argument("--until", type=str, default=None, help="Exclusive end YYYY-MM-DD (default: now)")
    p.add_argument(
        "--out",
        type=Path,
        default=Path("/app/exports/message_history_last_3_months.md"),
    )
    args = p.parse_args()
    since = _parse_date(args.since) if args.since else None
    until = _parse_date(args.until) if args.until else None
    days = args.days
    if since is None and days is None:
        days = 90
    stats = asyncio.run(export(args.out, days=days, since=since, until=until))
    print(stats)


if __name__ == "__main__":
    main()
