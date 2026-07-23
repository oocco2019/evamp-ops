"""
Mine repeated Instructions-for-AI prompts (and adherence themes) into pending ReplyInsight rows.
Insights are not injected into drafts until promoted to policy or playbook.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.messages import AIComposition, ReplyInsight, ReplyPlaybookEntry, ReplyPolicy

MIN_OCCURRENCES = 2
LOOKBACK = 80


def normalize_instruction_text(text: str) -> str:
    t = (text or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[\"'`]+", "", t)
    return t[:500]


def fingerprint_for(text: str, source: str = "extra_instructions") -> str:
    raw = f"{source}:{normalize_instruction_text(text)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _classify_kind_heuristic(text: str) -> str:
    """policy = how we write; playbook = what to suggest for a product/issue."""
    t = text.lower()
    playbook_markers = (
        "suggest",
        "ask the buyer",
        "ask customer",
        "check",
        "socket",
        "wifi",
        "ssid",
        "label",
        "return",
        "refund",
        "power",
        "cable",
        "plug",
        "firmware",
        "reset",
        "a4",
    )
    policy_markers = (
        "comma",
        "tone",
        "don't use",
        "do not use",
        "avoid",
        "never",
        "greeting",
        "timeline",
        "shortly",
        "friendly",
        ", and",
        "dash",
    )
    play_hits = sum(1 for m in playbook_markers if m in t)
    pol_hits = sum(1 for m in policy_markers if m in t)
    if play_hits > pol_hits:
        return "playbook"
    return "policy"


def _clean_candidate_body(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"\s+", " ", t)
    if t and t[0].islower():
        t = t[0].upper() + t[1:]
    if t and t[-1] not in ".!?":
        t = t + "."
    return t[:2000]


async def _existing_covers(db: AsyncSession, normalized: str) -> bool:
    """Skip if an enabled policy/playbook already contains this idea (substring)."""
    if len(normalized) < 12:
        return False
    # Use a distinctive chunk
    chunk = normalized[:80]
    pols = await db.execute(select(ReplyPolicy.body).where(ReplyPolicy.enabled == True))  # noqa: E712
    for (body,) in pols.all():
        if chunk in normalize_instruction_text(body or ""):
            return True
    pbs = await db.execute(
        select(ReplyPlaybookEntry.resolution, ReplyPlaybookEntry.symptom).where(
            ReplyPlaybookEntry.enabled == True  # noqa: E712
        )
    )
    for resolution, symptom in pbs.all():
        blob = normalize_instruction_text(f"{symptom or ''} {resolution or ''}")
        if chunk in blob:
            return True
    return False


async def _already_reviewed(
    db: AsyncSession,
    *,
    fingerprint: str,
    normalized: str,
) -> bool:
    """
    True if this rule was already suggested and the user promoted or dismissed it.
    Matches exact fingerprint or near-duplicate body text so we do not re-suggest.
    """
    by_fp = await db.execute(
        select(ReplyInsight).where(
            ReplyInsight.fingerprint == fingerprint,
            ReplyInsight.status.in_(("promoted", "dismissed")),
        )
    )
    if by_fp.scalar_one_or_none():
        return True

    if len(normalized) < 12:
        return False
    chunk = normalized[:80]
    reviewed = await db.execute(
        select(ReplyInsight.body, ReplyInsight.symptom, ReplyInsight.title).where(
            ReplyInsight.status.in_(("promoted", "dismissed"))
        )
    )
    for body, symptom, title in reviewed.all():
        blob = normalize_instruction_text(f"{title or ''} {symptom or ''} {body or ''}")
        if chunk in blob or (blob and blob[:80] in normalized):
            return True
    return False


async def consider_extra_instructions_insight(
    db: AsyncSession,
    *,
    composition: AIComposition,
    extra_instructions: Optional[str],
) -> Optional[ReplyInsight]:
    """
    If the same Instructions-for-AI text (normalized) appears >= MIN_OCCURRENCES
    across recent compositions, upsert a pending insight for review.
    Never re-suggest after promote or dismiss.
    """
    text = (extra_instructions or "").strip()
    if len(text) < 8:
        return None

    norm = normalize_instruction_text(text)
    fp = fingerprint_for(text, "extra_instructions")

    if await _already_reviewed(db, fingerprint=fp, normalized=norm):
        return None

    # Count recent compositions with same fingerprint in snapshot
    result = await db.execute(
        select(AIComposition)
        .order_by(AIComposition.id.desc())
        .limit(LOOKBACK)
    )
    recent = list(result.scalars().all())
    matching_ids: List[int] = []
    samples: List[str] = []
    for c in recent:
        snap = c.prompt_snapshot or {}
        extra = (snap.get("extra_instructions") or "").strip()
        if not extra:
            continue
        if fingerprint_for(extra, "extra_instructions") == fp:
            matching_ids.append(c.id)
            if len(samples) < 5:
                samples.append(extra[:300])

    # Current composition may not be in recent query yet if just flushed — ensure counted
    if composition.id and composition.id not in matching_ids:
        matching_ids.insert(0, composition.id)
        samples.insert(0, text[:300])

    count = len(matching_ids)
    if count < MIN_OCCURRENCES:
        return None

    if await _existing_covers(db, norm):
        return None

    existing = await db.execute(
        select(ReplyInsight).where(ReplyInsight.fingerprint == fp)
    )
    insight = existing.scalar_one_or_none()
    kind = _classify_kind_heuristic(text)
    body = _clean_candidate_body(text)
    evidence = {
        "composition_ids": matching_ids[:20],
        "samples": samples,
        "normalized": norm[:200],
    }

    if insight:
        # promoted/dismissed already handled by _already_reviewed; pending → refresh counts only
        if insight.status != "pending":
            return None
        insight.occurrence_count = count
        insight.evidence = evidence
        insight.updated_at = datetime.utcnow()
        if not insight.body:
            insight.body = body
        await db.flush()
        return insight

    insight = ReplyInsight(
        status="pending",
        kind=kind,
        fingerprint=fp,
        title=(body[:80] + "…") if len(body) > 80 else body,
        body=body,
        symptom=None if kind == "policy" else body[:200],
        sku_scope="*",
        source="extra_instructions",
        occurrence_count=count,
        evidence=evidence,
    )
    db.add(insight)
    await db.flush()
    return insight


async def consider_adherence_failure_insights(
    db: AsyncSession,
    *,
    composition: AIComposition,
) -> List[ReplyInsight]:
    """
    If the same adherence failure reason repeats across compositions, surface as policy insight.
    Never re-suggest after promote or dismiss.
    """
    adh = composition.adherence_json or {}
    final = adh.get("final") or {}
    results = final.get("results") or []
    created: List[ReplyInsight] = []
    for r in results:
        if r.get("pass"):
            continue
        reason = (r.get("reason") or "").strip()
        if len(reason) < 12:
            continue
        # Tie to policy id when present
        policy_id = r.get("policy_id")
        key_text = f"adherence:{policy_id}:{reason}"
        fp = fingerprint_for(key_text, "adherence")
        norm = normalize_instruction_text(reason)

        if await _already_reviewed(db, fingerprint=fp, normalized=norm):
            continue

        result = await db.execute(
            select(AIComposition)
            .order_by(AIComposition.id.desc())
            .limit(LOOKBACK)
        )
        count = 0
        samples: List[str] = []
        ids: List[int] = []
        for c in result.scalars().all():
            cj = c.adherence_json or {}
            for rr in (cj.get("final") or {}).get("results") or []:
                if rr.get("pass"):
                    continue
                if (rr.get("reason") or "").strip().lower() == reason.lower():
                    count += 1
                    ids.append(c.id)
                    if len(samples) < 5:
                        samples.append(reason[:300])
                    break
        if count < MIN_OCCURRENCES:
            continue

        existing = await db.execute(
            select(ReplyInsight).where(ReplyInsight.fingerprint == fp)
        )
        insight = existing.scalar_one_or_none()
        body = _clean_candidate_body(
            f"Strengthen or clarify the writing rule so this failure stops recurring: {reason}"
        )
        evidence = {"composition_ids": ids[:20], "samples": samples, "policy_id": policy_id}
        if insight:
            if insight.status != "pending":
                continue
            insight.occurrence_count = count
            insight.evidence = evidence
            insight.updated_at = datetime.utcnow()
            created.append(insight)
            continue

        insight = ReplyInsight(
            status="pending",
            kind="policy",
            fingerprint=fp,
            title=(reason[:80] + "…") if len(reason) > 80 else reason,
            body=body,
            sku_scope="*",
            source="adherence",
            occurrence_count=count,
            evidence=evidence,
        )
        db.add(insight)
        created.append(insight)
    if created:
        await db.flush()
    return created


async def mine_insights_after_composition(
    db: AsyncSession,
    *,
    composition: AIComposition,
    extra_instructions: Optional[str],
) -> None:
    await consider_extra_instructions_insight(
        db, composition=composition, extra_instructions=extra_instructions
    )
    await consider_adherence_failure_insights(db, composition=composition)


async def pending_insight_count(db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count())
        .select_from(ReplyInsight)
        .where(ReplyInsight.status == "pending")
    )
    return int(result.scalar() or 0)


async def promote_insight(db: AsyncSession, insight: ReplyInsight) -> Dict[str, Any]:
    """Create policy or playbook from insight; mark promoted."""
    if insight.status != "pending":
        raise ValueError("Only pending insights can be promoted")

    if insight.kind == "playbook":
        row = ReplyPlaybookEntry(
            symptom=(insight.symptom or insight.title or "").strip() or "General",
            resolution=insight.body.strip(),
            sku_scope=(insight.sku_scope or "*").strip() or "*",
            trigger_keywords=None,
            enabled=True,
        )
        db.add(row)
        await db.flush()
        insight.status = "promoted"
        insight.reviewed_at = datetime.utcnow()
        return {"promoted_as": "playbook", "id": row.id}

    row = ReplyPolicy(
        body=insight.body.strip(),
        enabled=True,
        sort_order=100,
    )
    db.add(row)
    await db.flush()
    insight.status = "promoted"
    insight.reviewed_at = datetime.utcnow()
    return {"promoted_as": "policy", "id": row.id}
