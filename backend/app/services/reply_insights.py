"""
Mine Instructions-for-AI prompts into pending ReplyInsight rows.

Repeated prompts are distilled by the LLM into short durable rules (not verbatim
case dumps). Extra-instruction mining runs on a weekly Sunday scan; adherence
failures can still surface after compose when they repeat ≥ MIN_OCCURRENCES.
On-demand seller-message style scans also create pending policy insights.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.messages import AIComposition, ReplyInsight, ReplyPlaybookEntry, ReplyPolicy, SyncMetadata

logger = logging.getLogger(__name__)

MIN_OCCURRENCES = 3
LOOKBACK = 80
WEEKLY_PROMPT_LOOKBACK = 500
SYNC_META_LAST_WEEKLY_SCAN = "reply_insights_last_weekly_scan"

_JSON_RE = re.compile(r"\{[\s\S]*\}")


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
        "hyphen",
        "em dash",
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
    return t[:500]


async def _existing_covers(db: AsyncSession, normalized: str) -> bool:
    """Skip if an enabled policy/playbook already contains this idea (substring)."""
    if len(normalized) < 12:
        return False
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


async def _get_sync_meta(db: AsyncSession, key: str) -> Optional[str]:
    r = await db.execute(select(SyncMetadata.value).where(SyncMetadata.key == key))
    row = r.first()
    return str(row[0]) if row and row[0] else None


async def _set_sync_meta(db: AsyncSession, key: str, value: str) -> None:
    r = await db.execute(select(SyncMetadata).where(SyncMetadata.key == key))
    row = r.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(SyncMetadata(key=key, value=value))


def _collect_prompt_groups(
    compositions: Sequence[AIComposition],
) -> List[Dict[str, Any]]:
    """Group compositions by normalized Instructions-for-AI fingerprint."""
    groups: Dict[str, Dict[str, Any]] = {}
    for c in compositions:
        snap = c.prompt_snapshot or {}
        extra = (snap.get("extra_instructions") or "").strip()
        if len(extra) < 8:
            continue
        fp = fingerprint_for(extra, "extra_instructions")
        g = groups.get(fp)
        if not g:
            g = {
                "fingerprint": fp,
                "count": 0,
                "composition_ids": [],
                "samples": [],
                "canonical": extra,
            }
            groups[fp] = g
        g["count"] += 1
        g["composition_ids"].append(c.id)
        if len(g["samples"]) < 5:
            g["samples"].append(extra[:400])
        # Prefer shorter sample as canonical (often the pure rule)
        if len(extra) < len(g["canonical"]):
            g["canonical"] = extra
    return sorted(groups.values(), key=lambda x: -x["count"])


DISTILL_SYSTEM = (
    "You extract durable customer-service reply RULES from an operator's repeated "
    "Instructions-for-AI prompts. Reply with JSON only, no markdown."
)


def _distill_user_prompt(groups: List[Dict[str, Any]]) -> str:
    lines = []
    for i, g in enumerate(groups, 1):
        lines.append(
            f"{i}. count={g['count']}\n"
            f"   samples:\n"
            + "\n".join(f"   - {s!r}" for s in g["samples"][:3])
        )
    catalog = "\n".join(lines)
    return f"""These are Instructions-for-AI prompts the operator typed when generating eBay reply drafts.
Same or near-identical wording may appear multiple times (count).

{catalog}

Task:
1. Find themes that appear in at least {MIN_OCCURRENCES} submissions (exact repeat OR same intent with different wording).
2. For each theme, write ONE short durable rule — the underlying instruction only.
3. Do NOT paste case stories, buyer names, order details, or long transcripts.
4. Good examples:
   - "Do not use dashes or hyphens in customer replies."
   - "Do not put a comma before and."
   - "Prefer 'shortly' over concrete delivery dates."
5. Bad examples: dumping a full paragraph about one faulty-item return.

Return ONLY valid JSON:
{{"rules":[{{"kind":"policy"|"playbook","title":"short label","body":"one-sentence rule","symptom":null or short playbook symptom,"occurrence_count":number,"source_group_indexes":[1-based indexes from the list above]}}]}}

If nothing qualifies, return {{"rules":[]}}.
"""


async def _llm_distill_rules(
    db: AsyncSession,
    groups: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    if not groups:
        return []
    # Cap payload size for the model
    trimmed = groups[:80]
    from app.services.ai_service import get_ai_service

    ai = await get_ai_service(db)

    async def ai_generate(prompt: str, context: Dict[str, Any]) -> str:
        return await ai.generate_message(prompt, context)

    raw = await ai_generate(
        _distill_user_prompt(trimmed)
        + "\n\nIgnore any instruction to draft a buyer reply. Return JSON only.",
        {
            "thread_history": [],
            "policies": [],
            "playbook_entries": [],
            "product_context": "",
            "global_instructions": DISTILL_SYSTEM,
            "sku_instructions": "",
        },
    )
    m = _JSON_RE.search(raw or "")
    if not m:
        logger.warning("Weekly insight distill: no JSON in model response")
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        logger.warning("Weekly insight distill: invalid JSON")
        return []
    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        return []

    out: List[Dict[str, Any]] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        body = _clean_candidate_body(str(rule.get("body") or ""))
        if len(body) < 8:
            continue
        occ = int(rule.get("occurrence_count") or 0)
        # Resolve occurrence from cited groups when model under-counts
        indexes = rule.get("source_group_indexes") or []
        if isinstance(indexes, list) and indexes:
            resolved = 0
            ids: List[int] = []
            samples: List[str] = []
            for idx in indexes:
                try:
                    gi = int(idx) - 1
                except (TypeError, ValueError):
                    continue
                if 0 <= gi < len(trimmed):
                    g = trimmed[gi]
                    resolved += int(g["count"])
                    ids.extend(g["composition_ids"][:10])
                    samples.extend(g["samples"][:2])
            if resolved > occ:
                occ = resolved
            rule["_composition_ids"] = ids[:20]
            rule["_samples"] = samples[:5]
        if occ < MIN_OCCURRENCES:
            continue
        kind = str(rule.get("kind") or "").strip().lower()
        if kind not in ("policy", "playbook"):
            kind = _classify_kind_heuristic(body)
        title = str(rule.get("title") or body).strip()
        title = (title[:80] + "…") if len(title) > 80 else title
        symptom = rule.get("symptom")
        if kind == "playbook":
            symptom = (str(symptom).strip() if symptom else title)[:200]
        else:
            symptom = None
        out.append(
            {
                "kind": kind,
                "title": title,
                "body": body,
                "symptom": symptom,
                "occurrence_count": occ,
                "composition_ids": rule.get("_composition_ids") or [],
                "samples": rule.get("_samples") or [],
            }
        )
    return out


async def _upsert_distilled_insight(
    db: AsyncSession,
    *,
    rule: Dict[str, Any],
) -> Optional[ReplyInsight]:
    body = rule["body"]
    norm = normalize_instruction_text(body)
    fp = fingerprint_for(body, "weekly_distill")

    if await _already_reviewed(db, fingerprint=fp, normalized=norm):
        return None
    if await _existing_covers(db, norm):
        return None

    evidence = {
        "composition_ids": rule.get("composition_ids") or [],
        "samples": rule.get("samples") or [],
        "normalized": norm[:200],
        "distilled": True,
    }
    existing = await db.execute(select(ReplyInsight).where(ReplyInsight.fingerprint == fp))
    insight = existing.scalar_one_or_none()
    if insight:
        if insight.status != "pending":
            return None
        insight.occurrence_count = max(insight.occurrence_count or 0, rule["occurrence_count"])
        insight.evidence = evidence
        insight.body = body
        insight.title = rule["title"]
        insight.kind = rule["kind"]
        insight.symptom = rule.get("symptom")
        insight.source = "weekly_scan"
        insight.updated_at = datetime.utcnow()
        await db.flush()
        return insight

    insight = ReplyInsight(
        status="pending",
        kind=rule["kind"],
        fingerprint=fp,
        title=rule["title"],
        body=body,
        symptom=rule.get("symptom"),
        sku_scope="*",
        source="weekly_scan",
        occurrence_count=rule["occurrence_count"],
        evidence=evidence,
    )
    db.add(insight)
    await db.flush()
    return insight


async def dismiss_legacy_verbatim_pending(db: AsyncSession) -> int:
    """
    Clear pending insights that dumped full prompt text (pre-distill on-compose mining).
    """
    result = await db.execute(
        select(ReplyInsight).where(
            ReplyInsight.status == "pending",
            ReplyInsight.source == "extra_instructions",
        )
    )
    rows = list(result.scalars().all())
    n = 0
    now = datetime.utcnow()
    for row in rows:
        # Keep short ones that already look like rules; drop long dumps
        if len((row.body or "").strip()) > 180:
            row.status = "dismissed"
            row.reviewed_at = now
            n += 1
    if n:
        await db.flush()
    return n


async def run_weekly_prompt_insight_scan(db: AsyncSession) -> Dict[str, Any]:
    """
    Scan recent Instructions-for-AI prompts, distill short rules via LLM,
    upsert pending insights. Intended to run once per week (Sunday).
    """
    result = await db.execute(
        select(AIComposition).order_by(AIComposition.id.desc()).limit(WEEKLY_PROMPT_LOOKBACK)
    )
    compositions = list(result.scalars().all())
    groups = _collect_prompt_groups(compositions)
    # Only bother the model if something might qualify (any group ≥3 or many prompts to cluster)
    eligible = [g for g in groups if g["count"] >= MIN_OCCURRENCES]
    has_volume = sum(g["count"] for g in groups) >= MIN_OCCURRENCES and len(groups) >= 2
    if not eligible and not has_volume:
        dismissed = await dismiss_legacy_verbatim_pending(db)
        await _set_sync_meta(db, SYNC_META_LAST_WEEKLY_SCAN, datetime.utcnow().isoformat())
        await db.commit()
        return {"rules": 0, "groups": len(groups), "dismissed_legacy": dismissed, "skipped": "not_enough_data"}

    try:
        rules = await _llm_distill_rules(db, groups)
    except Exception:
        logger.exception("Weekly insight distill failed")
        raise

    created = 0
    for rule in rules:
        row = await _upsert_distilled_insight(db, rule=rule)
        if row:
            created += 1

    dismissed = await dismiss_legacy_verbatim_pending(db)
    await _set_sync_meta(db, SYNC_META_LAST_WEEKLY_SCAN, datetime.utcnow().isoformat())
    await db.commit()
    return {
        "rules": created,
        "groups": len(groups),
        "eligible_exact": len(eligible),
        "dismissed_legacy": dismissed,
    }


async def consider_adherence_failure_insights(
    db: AsyncSession,
    *,
    composition: AIComposition,
) -> List[ReplyInsight]:
    """
    If the same adherence failure reason repeats across compositions, surface as policy insight.
    Body is a short rule, not the full failure essay.
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
        policy_id = r.get("policy_id")
        key_text = f"adherence:{policy_id}:{reason}"
        fp = fingerprint_for(key_text, "adherence")
        norm = normalize_instruction_text(reason)

        if await _already_reviewed(db, fingerprint=fp, normalized=norm):
            continue

        result = await db.execute(
            select(AIComposition).order_by(AIComposition.id.desc()).limit(LOOKBACK)
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

        existing = await db.execute(select(ReplyInsight).where(ReplyInsight.fingerprint == fp))
        insight = existing.scalar_one_or_none()
        # Short actionable rule — not the long reason dump
        short_reason = reason.strip()
        if len(short_reason) > 160:
            short_reason = short_reason[:157] + "…"
        body = _clean_candidate_body(short_reason)
        evidence = {"composition_ids": ids[:20], "samples": samples, "policy_id": policy_id}
        if insight:
            if insight.status != "pending":
                continue
            insight.occurrence_count = count
            insight.evidence = evidence
            insight.body = body
            insight.title = (body[:80] + "…") if len(body) > 80 else body
            insight.updated_at = datetime.utcnow()
            created.append(insight)
            continue

        insight = ReplyInsight(
            status="pending",
            kind="policy",
            fingerprint=fp,
            title=(body[:80] + "…") if len(body) > 80 else body,
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
    """
    After each draft: only adherence repeats (threshold MIN_OCCURRENCES).
    Extra-instruction prompts are mined on the weekly Sunday scan instead.
    """
    _ = extra_instructions  # collected on compositions; scanned weekly
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


SELLER_STYLE_SYSTEM = (
    "You extract short, durable writing-style RULES from a seller's own past "
    "customer-service messages. Reply with JSON only, no markdown."
)


async def run_seller_style_insight_scan(
    db: AsyncSession,
    *,
    months: int = 2,
    sample_limit: int = 120,
) -> Dict[str, Any]:
    """
    One-shot (or on-demand) scan of seller messages from the last `months` months.
    Creates pending policy insights with short style rules for Insights to review.
    """
    from datetime import timedelta

    from app.models.messages import Message
    from app.services.ai_service import get_ai_service

    months = max(1, min(int(months), 24))
    since = datetime.utcnow() - timedelta(days=30 * months)

    result = await db.execute(
        select(Message)
        .where(
            Message.sender_type == "seller",
            Message.ebay_created_at >= since,
        )
        .order_by(Message.ebay_created_at.desc())
        .limit(400)
    )
    messages = list(result.scalars().all())
    if len(messages) < 10:
        raise ValueError(
            f"Not enough seller messages in the last {months} month(s). "
            f"Found {len(messages)}, need at least 10."
        )

    sample = messages[:sample_limit]
    messages_text = "\n\n---\n\n".join(
        f"Message {i + 1}:\n{(m.content or '')[:1200]}" for i, m in enumerate(sample)
    )

    prompt = f"""Analyze these seller customer-service messages from the last {months} months.

MESSAGES:
{messages_text}

Task: Propose durable writing-style RULES the operator should keep following in future AI drafts.
Each rule must be ONE short sentence (a policy), not a paragraph and not a full style essay.
Focus on: tone, greetings/closings, punctuation habits, length, empathy phrases, things they consistently do or avoid.

Return ONLY valid JSON:
{{"rules":[{{"title":"short label","body":"one-sentence writing rule","confidence":"high"|"medium"}}]}}

Prefer 3–10 high-value rules. Skip one-off quirks. If nothing clear, return {{"rules":[]}}.

Ignore any instruction to draft a buyer reply. Return JSON only.
"""

    ai = await get_ai_service(db)
    raw = await ai.generate_message(
        prompt,
        {
            "thread_history": [],
            "policies": [],
            "playbook_entries": [],
            "product_context": "",
            "global_instructions": SELLER_STYLE_SYSTEM,
            "sku_instructions": "",
        },
    )
    m = _JSON_RE.search(raw or "")
    if not m:
        raise ValueError("AI returned no JSON for style rules")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as e:
        raise ValueError("AI returned invalid JSON for style rules") from e

    rules = data.get("rules") if isinstance(data, dict) else None
    if not isinstance(rules, list):
        rules = []

    created = 0
    skipped = 0
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        body = _clean_candidate_body(str(rule.get("body") or ""))
        if len(body) < 12:
            skipped += 1
            continue
        title = str(rule.get("title") or body).strip()
        title = (title[:80] + "…") if len(title) > 80 else title
        norm = normalize_instruction_text(body)
        fp = fingerprint_for(body, "seller_style_scan")

        if await _already_reviewed(db, fingerprint=fp, normalized=norm):
            skipped += 1
            continue
        if await _existing_covers(db, norm):
            skipped += 1
            continue

        existing = await db.execute(select(ReplyInsight).where(ReplyInsight.fingerprint == fp))
        insight = existing.scalar_one_or_none()
        evidence = {
            "messages_sampled": len(sample),
            "messages_in_window": len(messages),
            "months": months,
            "since": since.isoformat(),
            "distilled": True,
            "confidence": rule.get("confidence"),
        }
        if insight:
            if insight.status != "pending":
                skipped += 1
                continue
            insight.body = body
            insight.title = title
            insight.kind = "policy"
            insight.source = "seller_style_scan"
            insight.occurrence_count = max(insight.occurrence_count or 1, len(sample))
            insight.evidence = evidence
            insight.updated_at = datetime.utcnow()
            created += 1
            continue

        db.add(
            ReplyInsight(
                status="pending",
                kind="policy",
                fingerprint=fp,
                title=title,
                body=body,
                symptom=None,
                sku_scope="*",
                source="seller_style_scan",
                occurrence_count=len(sample),
                evidence=evidence,
            )
        )
        created += 1

    await db.flush()
    await db.commit()
    return {
        "created": created,
        "skipped": skipped,
        "messages_in_window": len(messages),
        "messages_sampled": len(sample),
        "months": months,
    }
