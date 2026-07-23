"""
Reply policy / playbook helpers for AI message composition.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.messages import (
    AIComposition,
    MessageThread,
    ReplyPlaybookEntry,
    ReplyPolicy,
)
from app.models.stock import LineItem, Order, SKU


def sku_matches_scope(sku: Optional[str], scope: str) -> bool:
    """
    Match SKU against scope:
    - `*` — all
    - exact code
    - prefix with trailing `*` (e.g. dee*)
    - comma-separated list of any of the above (e.g. dee01, dee02, uke01)
    """
    scope = (scope or "*").strip()
    if not scope or scope == "*":
        return True
    parts = [p.strip() for p in scope.split(",") if p.strip()]
    if not parts:
        return True
    if any(p == "*" for p in parts):
        return True
    if not sku:
        return False
    sku_l = sku.strip().lower()
    for part in parts:
        part_l = part.lower()
        if part_l.endswith("*") and not part_l.startswith("*"):
            if sku_l.startswith(part_l[:-1]):
                return True
        elif sku_l == part_l:
            return True
    return False


def playbook_matches_keywords(
    thread_text: str,
    keywords: Optional[Sequence[str]],
) -> bool:
    """No keywords → match all; else any keyword appears case-insensitively."""
    if not keywords:
        return True
    hay = (thread_text or "").lower()
    for kw in keywords:
        k = (kw or "").strip().lower()
        if k and k in hay:
            return True
    return False


def thread_text_from_history(thread_history: List[Dict[str, Any]]) -> str:
    parts = []
    for msg in thread_history:
        parts.append((msg.get("content") or "").strip())
    return "\n".join(parts)


async def resolve_product_context(
    db: AsyncSession,
    thread: MessageThread,
    ebay_order_id: Optional[str],
) -> Dict[str, Any]:
    """
    Resolve order → line SKUs → titles.
    Falls back to thread.sku / SKU catalog when order missing.
    """
    skus: List[str] = []
    titles: List[str] = []
    order_id = (ebay_order_id or thread.ebay_order_id or "").strip() or None

    if order_id:
        result = await db.execute(
            select(Order)
            .where(Order.ebay_order_id == order_id)
            .options(selectinload(Order.line_items))
            .limit(1)
        )
        order = result.scalar_one_or_none()
        if order and order.line_items:
            for li in order.line_items:
                code = (li.sku or "").strip()
                if code and code not in skus:
                    skus.append(code)

    if not skus and thread.sku:
        skus.append(thread.sku.strip())

    for code in skus:
        row = await db.get(SKU, code)
        titles.append(row.title if row and row.title else code)

    primary_sku = skus[0] if skus else (thread.sku or None)
    lines = []
    if order_id:
        lines.append(f"Order ID: {order_id}")
    if skus:
        for code, title in zip(skus, titles):
            lines.append(f"SKU: {code} — {title}")
    elif thread.sku:
        lines.append(f"SKU: {thread.sku}")

    return {
        "order_id": order_id,
        "skus": skus,
        "titles": titles,
        "primary_sku": primary_sku,
        "product_context_text": "\n".join(lines) if lines else "",
    }


async def load_enabled_policies(db: AsyncSession) -> List[ReplyPolicy]:
    result = await db.execute(
        select(ReplyPolicy)
        .where(ReplyPolicy.enabled == True)  # noqa: E712
        .order_by(ReplyPolicy.sort_order, ReplyPolicy.id)
    )
    return list(result.scalars().all())


async def retrieve_playbook_entries(
    db: AsyncSession,
    *,
    skus: Sequence[str],
    thread_text: str,
) -> List[ReplyPlaybookEntry]:
    """Match by SKU scope only (`*` = all). Keywords are not used for retrieval."""
    del thread_text  # reserved for future use; matching is SKU-scope only
    result = await db.execute(
        select(ReplyPlaybookEntry).where(ReplyPlaybookEntry.enabled == True)  # noqa: E712
    )
    entries = list(result.scalars().all())
    matched: List[ReplyPlaybookEntry] = []
    sku_list = [s for s in skus if s] or [None]
    for entry in entries:
        if any(sku_matches_scope(s, entry.sku_scope) for s in sku_list):
            matched.append(entry)
    return matched


def build_compose_prompt_parts(
    policies: Sequence[ReplyPolicy],
    playbook: Sequence[ReplyPlaybookEntry],
    product_context_text: str,
    extra_instructions: Optional[str],
) -> Tuple[str, Dict[str, Any]]:
    """User-side compose instruction (system prompt carries policies/playbook too)."""
    prompt = "Draft a reply to this customer message."
    if product_context_text:
        prompt += f"\n\nPRODUCT CONTEXT:\n{product_context_text}"
    if playbook:
        prompt += "\n\nRELEVANT PLAYBOOK (use when it applies; do not invent conflicting facts):"
        for i, e in enumerate(playbook, 1):
            sym = (e.symptom or "").strip()
            res = (e.resolution or "").strip()
            block = f"\n{i}. "
            if sym:
                block += f"Symptom: {sym}\n   Resolution: {res}"
            else:
                block += res
            prompt += block
    if extra_instructions and extra_instructions.strip():
        prompt += f"\n\nAdditional instructions: {extra_instructions.strip()}"
    snapshot = {
        "prompt": prompt,
        "extra_instructions": (extra_instructions or "").strip() or None,
        "policy_bodies": [p.body for p in policies],
        "playbook": [
            {"id": e.id, "symptom": e.symptom, "resolution": e.resolution, "sku_scope": e.sku_scope}
            for e in playbook
        ],
        "product_context": product_context_text,
    }
    return prompt, snapshot


def build_provider_context(
    *,
    thread_history: List[Dict[str, Any]],
    policies: Sequence[ReplyPolicy],
    playbook: Sequence[ReplyPlaybookEntry],
    product_context_text: str,
) -> Dict[str, Any]:
    return {
        "thread_history": thread_history,
        "policies": [{"id": p.id, "body": p.body} for p in policies],
        "playbook_entries": [
            {
                "id": e.id,
                "symptom": e.symptom or "",
                "resolution": e.resolution,
                "sku_scope": e.sku_scope,
            }
            for e in playbook
        ],
        "product_context": product_context_text,
        # Back-compat keys unused by new builders
        "global_instructions": "",
        "sku_instructions": "",
    }


_ADHERENCE_JSON_RE = re.compile(r"\{[\s\S]*\}")


async def run_adherence_check(
    ai_generate,
    *,
    draft: str,
    policies: Sequence[ReplyPolicy],
) -> Dict[str, Any]:
    """
    Second-pass: evaluate draft against each policy.
    ai_generate(prompt, context) -> str
    Returns { results: [{policy_id, pass, reason}], all_passed: bool }
    """
    if not policies:
        return {"results": [], "all_passed": True, "raw": None}

    policy_lines = "\n".join(f"{i}. [id={p.id}] {p.body}" for i, p in enumerate(policies, 1))
    check_prompt = f"""Evaluate this draft customer-service reply against each policy below.
Return ONLY valid JSON of the form:
{{"results":[{{"policy_id":1,"pass":true,"reason":"one line"}},...]}}
Use the exact policy id integers given. pass=true if the draft complies; false if it violates.

POLICIES:
{policy_lines}

DRAFT:
{draft}
"""
    raw = await ai_generate(
        check_prompt,
        {
            "thread_history": [],
            "policies": [],
            "playbook_entries": [],
            "product_context": "",
            "global_instructions": (
                "You are a strict policy checker. Reply with JSON only, no markdown."
            ),
            "sku_instructions": "",
        },
    )
    parsed = _parse_adherence_json(raw, policies)
    return parsed


def _parse_adherence_json(raw: str, policies: Sequence[ReplyPolicy]) -> Dict[str, Any]:
    results: List[Dict[str, Any]] = []
    try:
        m = _ADHERENCE_JSON_RE.search(raw or "")
        data = json.loads(m.group(0) if m else (raw or "{}"))
        by_id = {int(r["policy_id"]): r for r in data.get("results", []) if "policy_id" in r}
    except Exception:
        by_id = {}

    for p in policies:
        row = by_id.get(p.id)
        if row is None:
            results.append(
                {
                    "policy_id": p.id,
                    "pass": True,
                    "reason": "Could not parse adherence result; treating as pass",
                }
            )
        else:
            results.append(
                {
                    "policy_id": p.id,
                    "pass": bool(row.get("pass")),
                    "reason": str(row.get("reason") or "")[:300],
                }
            )
    all_passed = all(r["pass"] for r in results) if results else True
    return {"results": results, "all_passed": all_passed, "raw": (raw or "")[:4000]}


async def revise_draft_for_violations(
    ai_generate,
    *,
    draft: str,
    thread_history: List[Dict[str, Any]],
    policies: Sequence[ReplyPolicy],
    playbook: Sequence[ReplyPlaybookEntry],
    product_context_text: str,
    failures: List[Dict[str, Any]],
) -> str:
    fail_lines = []
    policy_by_id = {p.id: p for p in policies}
    for f in failures:
        pol = policy_by_id.get(f["policy_id"])
        body = pol.body if pol else f"policy {f['policy_id']}"
        fail_lines.append(f"- {body} (reason: {f.get('reason')})")
    revise_prompt = f"""Revise the draft reply so it complies with the failed policies below.
Keep the same meaning and helpfulness. Output only the revised message text.

FAILED POLICIES:
{chr(10).join(fail_lines)}

CURRENT DRAFT:
{draft}
"""
    ctx = build_provider_context(
        thread_history=thread_history,
        policies=policies,
        playbook=playbook,
        product_context_text=product_context_text,
    )
    return (await ai_generate(revise_prompt, ctx)).strip()


async def compose_draft_with_adherence(
    db: AsyncSession,
    *,
    thread: MessageThread,
    thread_history: List[Dict[str, Any]],
    ebay_order_id: Optional[str],
    extra_instructions: Optional[str],
    ai_generate,
    max_revises: int = 2,
) -> Tuple[str, AIComposition]:
    """
    Full compose: resolve product, policies, playbook, generate, adhere ≤ max_revises.
    Persists AIComposition and returns (draft, composition).
    """
    product = await resolve_product_context(db, thread, ebay_order_id)
    policies = await load_enabled_policies(db)
    text = thread_text_from_history(thread_history)
    playbook = await retrieve_playbook_entries(
        db, skus=product["skus"] or ([product["primary_sku"]] if product["primary_sku"] else []), thread_text=text
    )
    # Broad playbook with no keywords and sku * should match; also match label-related when keywords empty.
    prompt, snapshot = build_compose_prompt_parts(
        policies, playbook, product["product_context_text"], extra_instructions
    )
    ctx = build_provider_context(
        thread_history=thread_history,
        policies=policies,
        playbook=playbook,
        product_context_text=product["product_context_text"],
    )
    draft = (await ai_generate(prompt, ctx)).strip()

    adherence_rounds: List[Dict[str, Any]] = []
    revise_count = 0
    last_adh: Dict[str, Any] = {"results": [], "all_passed": True}

    for _ in range(max_revises + 1):
        last_adh = await run_adherence_check(ai_generate, draft=draft, policies=policies)
        adherence_rounds.append({**last_adh, "revise_count": revise_count})
        if last_adh["all_passed"]:
            break
        if revise_count >= max_revises:
            break
        failures = [r for r in last_adh["results"] if not r["pass"]]
        draft = await revise_draft_for_violations(
            ai_generate,
            draft=draft,
            thread_history=thread_history,
            policies=policies,
            playbook=playbook,
            product_context_text=product["product_context_text"],
            failures=failures,
        )
        revise_count += 1

    composition = AIComposition(
        thread_id=thread.thread_id,
        sku=product.get("primary_sku"),
        order_id=product.get("order_id"),
        prompt_snapshot=snapshot,
        policy_ids=[p.id for p in policies],
        playbook_ids=[e.id for e in playbook],
        model_output=draft,
        adherence_json={
            "revise_count": revise_count,
            "final": last_adh,
            "rounds": adherence_rounds,
        },
    )
    db.add(composition)
    await db.flush()
    from app.services.reply_insights import mine_insights_after_composition

    await mine_insights_after_composition(
        db,
        composition=composition,
        extra_instructions=extra_instructions,
    )
    return draft, composition
