"""Persist OC GetStockMovement lines to PostgreSQL (idempotent upserts; rows are not TTL-pruned by this app)."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select, func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import OCStockMovementLine


_OC_TIME_RE = re.compile(r"^(.+)([+-])(\d{2})(\d{2})$")


def parse_oc_update_time_to_utc_naive(s: Optional[str]) -> Optional[datetime]:
    """Parse OC time strings like 2024-07-15T19:48:37+0800 to naive UTC."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    m = _OC_TIME_RE.match(s)
    if m:
        base, sign, zh, zm = m.groups()
        s = f"{base}{sign}{zh}:{zm}"
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:
            return dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt
    except ValueError:
        return None


async def persist_oc_stock_movement_lines(
    db: AsyncSession,
    connection_id: int,
    rows: List[Dict[str, Any]],
) -> int:
    """Insert movement rows; skip duplicates on (connection_id, movement_id). Returns newly inserted count."""
    if not rows:
        return 0
    payloads: List[Dict[str, Any]] = []
    for r in rows:
        mid = str(r.get("movement_id") or "").strip()
        if not mid:
            continue
        ut_raw = str(r.get("update_time") or "").strip()
        payloads.append(
            {
                "connection_id": connection_id,
                "mfskuid": str(r.get("mfskuid") or "").strip() or "",
                "seller_skuid": r.get("seller_skuid"),
                "service_region": str(r.get("service_region") or "").strip(),
                "inventory_status": str(r.get("inventory_status") or "").strip(),
                "movement_id": mid,
                "quantity": int(r.get("quantity") or 0),
                "actual_count": r.get("actual_count"),
                "reason": r.get("reason"),
                "order_number": r.get("order_number"),
                "update_time_raw": ut_raw,
                "update_time_utc": parse_oc_update_time_to_utc_naive(ut_raw),
            }
        )
    if not payloads:
        return 0
    inserted = 0
    batch = 400
    for i in range(0, len(payloads), batch):
        chunk = payloads[i : i + batch]
        stmt = pg_insert(OCStockMovementLine).values(chunk)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_oc_stock_mov_conn_movement")
        res = await db.execute(stmt)
        rc = res.rowcount
        if rc is not None:
            inserted += int(rc)
    return inserted


async def max_movement_update_time_utc(db: AsyncSession, connection_id: int) -> Optional[datetime]:
    event_time = func.coalesce(OCStockMovementLine.update_time_utc, OCStockMovementLine.created_at)
    r = await db.execute(
        select(func.max(event_time)).where(
            OCStockMovementLine.connection_id == connection_id
        )
    )
    return r.scalar_one_or_none()
