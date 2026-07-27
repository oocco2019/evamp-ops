"""
Rule-based CS reply router (language → intent → known-issue → tier/stage).

No LLM calls. Used by Messages-Test compose path.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.messages import KnownIssue, Message, MessageThread
from app.services.reply_compose import sku_matches_scope

# --- Intent keyword tables (priority: first match wins). "error" intentionally omitted. ---

_INTENT_PRIORITY: List[tuple[str, List[str]]] = [
    (
        "safety_claim",
        [
            "burnt",
            "burned",
            "melted",
            "fire",
            "smoke",
            "shock",
            "sparks",
            "tripped breaker",
            "electric shock",
            "brandgeruch",
            "geschmolzen",
            "rauch",
            "funken",
        ],
    ),
    (
        "not_charging",
        [
            "won't charge",
            "wont charge",
            "doesn't charge",
            "does not charge",
            "not charging",
            "stops charging",
            "no charge",
            "leakage",
            "lädt nicht",
            "laedt nicht",
            "lädt nicht",
            "kein laden",
        ],
    ),
    (
        "physical_fault",
        [
            "front off",
            "cover off",
            "glass off",
            "panel fell",
            "panel off",
            "cracked",
            "broken glass",
            "waterproof",
            "front fell",
            "abgefallen",
            "gerissen",
            "kaputt",
        ],
    ),
    (
        "not_arrived",
        [
            "not arrived",
            "still waiting",
            "where is",
            "where's my",
            "not received",
            "delay",
            "noch nicht",
            "nicht angekommen",
            "wo ist meine",
            "tracking",
        ],
    ),
    (
        "return_request",
        [
            "return",
            "refund",
            "send it back",
            "send back",
            "wrong length",
            "ordered wrong",
            "change the order",
            "rückgabe",
            "ruckgabe",
            "zurücksenden",
            "zuruecksenden",
            "erstattung",
        ],
    ),
    (
        "wrong_item",
        [
            "wrong one",
            "wrong item",
            "different cable",
            "not what i ordered",
            "received 5m",
            "received 10m",
            "falsche",
            "nicht bestellt",
        ],
    ),
    (
        "cancel",
        [
            "cancel",
            "bought by mistake",
            "klarna",
            "wrong payment",
            "stornieren",
            "storno",
        ],
    ),
    (
        "wifi_app",
        [
            "wifi",
            "wi-fi",
            "wlan",
            "app",
            "pair",
            "pairing",
            "connect",
            "koppeln",
            "timeout",
            "verbind",
        ],
    ),
    (
        "fitment",
        [
            "compatible",
            "will this fit",
            "suitable",
            "passt",
            "kompatibel",
            "reg ",
            "number plate",
            "kennzeichen",
        ],
    ),
    (
        "invoice",
        [
            "invoice",
            "vat invoice",
            "receipt",
            "rechnung",
            "mwst",
        ],
    ),
]

_DE_STOPWORDS = {
    "und",
    "der",
    "die",
    "das",
    "ich",
    "nicht",
    "mit",
    "für",
    "fuer",
    "bitte",
    "habe",
    "Hallo",
    "hallo",
    "noch",
    "schon",
    "wenn",
    "aber",
    "auch",
    "oder",
    "sehr",
    "danke",
    "guten",
    "tag",
}

_EN_STOPWORDS = {
    "the",
    "and",
    "for",
    "you",
    "please",
    "have",
    "this",
    "that",
    "with",
    "from",
    "hello",
    "thanks",
    "thank",
}

_FAIL_PHRASES = [
    "still",
    "same problem",
    "same issue",
    "didn't work",
    "did not work",
    "doesn't work",
    "does not work",
    "tried that",
    "already tried",
    "no change",
    "nicht geholfen",
    "immer noch",
    "gleiches problem",
    "hat nicht funktioniert",
]

_TROUBLESHOOT_SELLER = [
    "try",
    "check",
    "different socket",
    "another outlet",
    "reset",
    "troubleshoot",
    "can you",
    "please try",
    "testen",
    "prüfen",
    "pruefen",
]

_VIDEO_ASK = ["video", "whatsapp", "short clip", "film", "aufnahme"]
_VIDEO_GOT = ["video", "whatsapp", "sent a video", "clip", "youtube", "drive.google"]
_PHOTO_ASK = ["photo", "picture", "pic of", "foto", "bild"]
_PROMISE_UPDATE = [
    r"keep you updated",
    r"let you know",
    r"i'?ll check",
    r"i will check",
    r"get back to you",
    r"melde mich",
    r"rückmeldung",
    r"rueckmeldung",
]

_EBAY_CASE = [
    "ebay case",
    "eBay case",
    "money back guarantee",
    "opened a case",
    "return request on ebay",
    "escalat",
    "inr case",
]

# Most recent seller message: refusal / closure / decision (respect — do not overturn).
_SELLER_DECISION_PHRASES = [
    "unfortunately",
    "not able to",
    "can't offer",
    "cannot offer",
    "cant offer",
    "outside",
    "out of warranty",
    "expired",
    "past the",
    "unable to accept",
    "won't be able",
    "wont be able",
    "will not be able",
    "have to decline",
    "not covered",
    "denied",
    "can't accept",
    "cannot accept",
    "cant accept",
    "can't replace",
    "cannot replace",
    "no longer covered",
    "beyond the warranty",
    "warranty has ended",
    "warranty period",
]

# Buyer pushback after a seller decision: only draft normally if material is new.
_NEW_MATERIAL_KEYWORDS = [
    "photo",
    "picture",
    "screenshot",
    "video",
    "receipt",
    "invoice",
    "order number",
    "order #",
    "order id",
    "purchased on",
    "bought on",
    "ordered on",
    "within warranty",
    "still under warranty",
    "proof",
    "attached",
    "attachment",
    "here is the",
    "here's the",
    "datum",
    "bestellnummer",
    "rechnung",
    "foto",
    "bild",
]
_DATE_OR_ORDER_RE = re.compile(
    r"(?:\b\d{1,2}[./\-]\d{1,2}[./\-]\d{2,4}\b)"
    r"|(?:\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b)"
    r"|(?:\b\d{2,}-\d{4,}-\d{4,}\b)",  # rough eBay-ish order id shape
    re.I,
)

_STYLE_PACK = (
    "You are drafting an eBay seller reply for Evamp. "
    "Be warm, brief, and human. One short message only — never dump the whole support process. "
    "Do not invent order facts, tracking, or promises not supported by the thread or instructions. "
    "Never overturn a decision the seller already stated in this thread. "
    "Prefer plain punctuation; avoid em-dashes and stiff corporate phrasing."
)


@dataclass
class RouterResult:
    language: str
    intent: str
    tier: int
    stage: str
    known_issue_id: Optional[str] = None
    known_issue: Optional[Dict[str, Any]] = None
    reasons: List[str] = field(default_factory=list)
    flags: Dict[str, bool] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_language(text: str, stored_lang: Optional[str] = None) -> str:
    """Cheap EN | DE | OTHER. Prefer stored message language when present."""
    if stored_lang:
        sl = stored_lang.strip().lower()[:2]
        if sl == "de":
            return "DE"
        if sl == "en":
            return "EN"
    raw = text or ""
    lower = raw.lower()
    # German diacritics / ß
    if re.search(r"[äöüÄÖÜß]", raw):
        return "DE"
    tokens = re.findall(r"[a-zA-ZäöüÄÖÜß]+", lower)
    if not tokens:
        return "OTHER"
    de_hits = sum(1 for t in tokens if t in {w.lower() for w in _DE_STOPWORDS})
    en_hits = sum(1 for t in tokens if t in _EN_STOPWORDS)
    if de_hits >= 2 and de_hits > en_hits:
        return "DE"
    if en_hits >= 2 and en_hits >= de_hits:
        return "EN"
    # Common German words alone
    if any(w in lower for w in ("nicht", "bitte", "danke", "rechnung", "rück", "gerät", "geraet")):
        return "DE"
    if en_hits or de_hits:
        return "EN" if en_hits >= de_hits else "DE"
    return "OTHER"


def classify_intent(text: str) -> str:
    hay = (text or "").lower()
    for intent, phrases in _INTENT_PRIORITY:
        for p in phrases:
            if p.lower() in hay:
                return intent
    return "other"


def _buyer_has_image(message: Optional[Message]) -> bool:
    if not message or not message.media:
        return False
    media = message.media
    if isinstance(media, list) and len(media) > 0:
        return True
    return False


def match_known_issue(
    issues: Sequence[KnownIssue],
    *,
    text: str,
    skus: Sequence[str],
    has_image: bool,
) -> Optional[KnownIssue]:
    hay = (text or "").lower()
    sku_list = [s for s in skus if s] or [None]
    for issue in issues:
        if not issue.active:
            continue
        if issue.requires_image and not has_image:
            continue
        if not any(sku_matches_scope(s, issue.applies_to_sku) for s in sku_list):
            continue
        kws = issue.symptom_keywords or []
        if any((kw or "").lower() in hay for kw in kws if kw):
            return issue
    return None


def _latest_seller_message(messages: Sequence[Message]) -> Optional[Message]:
    sellers = [m for m in messages if (m.sender_type or "").lower() == "seller"]
    return sellers[-1] if sellers else None


def seller_already_decided(messages: Sequence[Message]) -> bool:
    """True if the most recent seller message contains a refusal/closure signal."""
    last_seller = _latest_seller_message(messages)
    if not last_seller:
        return False
    hay = (last_seller.content or "").lower()
    return any(p in hay for p in _SELLER_DECISION_PHRASES)


def _message_has_material_info(message: Optional[Message]) -> bool:
    if not message:
        return False
    if _buyer_has_image(message):
        return True
    hay = (message.content or "").lower()
    if any(k in hay for k in _NEW_MATERIAL_KEYWORDS):
        return True
    if _DATE_OR_ORDER_RE.search(message.content or ""):
        return True
    return False


def buyer_new_material_after_decision(messages: Sequence[Message]) -> bool:
    """
    True when a buyer message *after* the latest seller decision brings new evidence
    (attachment, date/order id, or evidence keyword). No buyer reply after the decision
    means no new material (hold the line — don't draft a reversal of the seller's last word).
    """
    msgs = sorted(messages, key=lambda m: m.ebay_created_at or datetime.min)
    if not seller_already_decided(msgs):
        return False
    seller_idxs = [
        i for i, m in enumerate(msgs) if (m.sender_type or "").lower() == "seller"
    ]
    if not seller_idxs:
        return False
    idx = seller_idxs[-1]
    after = [
        m for m in msgs[idx + 1 :] if (m.sender_type or "").lower() == "buyer"
    ]
    if not after:
        return False
    return _message_has_material_info(after[-1])


def _thread_signals(messages: Sequence[Message]) -> Dict[str, bool]:
    msgs = sorted(messages, key=lambda m: m.ebay_created_at or datetime.min)
    seller_blob = "\n".join(
        (m.content or "") for m in msgs if (m.sender_type or "").lower() == "seller"
    ).lower()
    buyer_msgs = [m for m in msgs if (m.sender_type or "").lower() == "buyer"]
    last_buyer = (buyer_msgs[-1].content or "").lower() if buyer_msgs else ""
    all_buyer = "\n".join((m.content or "") for m in buyer_msgs).lower()

    prior_ts = any(p in seller_blob for p in _TROUBLESHOOT_SELLER)
    seller_asked_video = any(p in seller_blob for p in _VIDEO_ASK)
    seller_asked_photo = any(p in seller_blob for p in _PHOTO_ASK)
    fail = any(p in last_buyer for p in _FAIL_PHRASES)
    video_received = seller_asked_video and any(p in all_buyer for p in _VIDEO_GOT)
    # Evidence "obvious" if buyer describes detached cover etc. with image already handled via known-issue
    evidence_obvious = bool(
        re.search(r"(front|cover|glass).{0,20}(off|fell|fallen)", last_buyer)
        or re.search(r"(panel).{0,20}(off|fell|lifted)", last_buyer)
    )
    decided = seller_already_decided(msgs)
    new_material = buyer_new_material_after_decision(msgs) if decided else False
    return {
        "prior_troubleshooting": prior_ts,
        "buyer_confirms_failed": fail,
        "video_received": video_received,
        "seller_asked_video": seller_asked_video,
        "seller_asked_photo": seller_asked_photo,
        "evidence_obvious": evidence_obvious,
        "seller_already_decided": decided,
        "buyer_new_material_info": new_material,
        "no_new_material_info": decided and not new_material,
    }


def _out_of_warranty(order_date: Optional[datetime]) -> bool:
    if not order_date:
        return False
    return order_date < datetime.utcnow() - timedelta(days=365)


def _ebay_case_flag(text: str) -> bool:
    hay = (text or "").lower()
    return any(p.lower() in hay for p in _EBAY_CASE)


def resolve_skip_action(issue: KnownIssue) -> str:
    """Apply batch_safe: white_glue replace only when batch_safe else refund."""
    action = (issue.skip_to_action or "none").strip()
    if issue.issue_id == "white_glue_cover":
        if issue.batch_safe and action == "resolve_replace":
            return "resolve_replace"
        return "resolve_refund"
    return action


def route(
    *,
    language: str,
    intent: str,
    known: Optional[KnownIssue],
    signals: Dict[str, bool],
    out_of_warranty: bool,
    ebay_case: bool,
) -> RouterResult:
    reasons: List[str] = []
    flags = {
        "out_of_warranty": out_of_warranty,
        "ebay_case": ebay_case,
        **signals,
    }

    # Safety / case / OOW → Tier 3
    if intent == "safety_claim" or ebay_case or out_of_warranty:
        reasons.append("tier3:safety_or_case_or_oow")
        hint_stage = "request_photo" if known and known.issue_id == "melted_plug" else "clarify"
        return RouterResult(
            language=language,
            intent=intent,
            tier=3,
            stage=hint_stage,
            known_issue_id=known.issue_id if known else None,
            known_issue=_issue_dict(known) if known else None,
            reasons=reasons,
            flags=flags,
        )

    # melted_plug always Tier 3 even if intent classified as physical_fault
    if known and known.issue_id == "melted_plug":
        reasons.append("tier3:melted_plug_safety")
        return RouterResult(
            language=language,
            intent=intent if intent != "other" else "safety_claim",
            tier=3,
            stage="request_photo",
            known_issue_id=known.issue_id,
            known_issue=_issue_dict(known),
            reasons=reasons,
            flags=flags,
        )

    # Respect seller's own prior decision when buyer brings nothing new
    if signals.get("seller_already_decided") and not signals.get("buyer_new_material_info"):
        reasons.append("tier3:seller_already_decided_hold_line")
        return RouterResult(
            language=language,
            intent=intent,
            tier=3,
            stage="clarify",
            known_issue_id=known.issue_id if known else None,
            known_issue=_issue_dict(known) if known else None,
            reasons=reasons,
            flags=flags,
        )

    if intent == "return_request" and language == "DE":
        reasons.append("tier3:de_return_not_free_returns")
        return RouterResult(
            language=language,
            intent=intent,
            tier=3,
            stage="arrange_return",
            known_issue_id=known.issue_id if known else None,
            known_issue=_issue_dict(known) if known else None,
            reasons=reasons,
            flags=flags,
        )

    # Tier 1 intents
    if intent in {"fitment", "invoice", "wifi_app", "cancel"}:
        stage_map = {
            "fitment": "fitment",
            "invoice": "invoice",
            "wifi_app": "wifi_guide",
            "cancel": "cancel",
        }
        if known and known.issue_id == "wifi_timeout":
            stage = "wifi_guide"
        else:
            stage = stage_map[intent]
        reasons.append(f"tier1:{intent}")
        return RouterResult(
            language=language,
            intent=intent,
            tier=1,
            stage=stage,
            known_issue_id=known.issue_id if known else None,
            known_issue=_issue_dict(known) if known else None,
            reasons=reasons,
            flags=flags,
        )

    if intent in {"return_request", "wrong_item"} and language != "DE":
        reasons.append("tier2:arrange_return")
        return RouterResult(
            language=language,
            intent=intent,
            tier=2,
            stage="arrange_return",
            known_issue_id=known.issue_id if known else None,
            known_issue=_issue_dict(known) if known else None,
            reasons=reasons,
            flags=flags,
        )

    # Tier 2 fault / delivery path
    if intent in {"not_charging", "physical_fault", "not_arrived"} or known:
        stage = _pick_tier2_stage(intent, known, signals, reasons)
        return RouterResult(
            language=language,
            intent=intent,
            tier=2,
            stage=stage,
            known_issue_id=known.issue_id if known else None,
            known_issue=_issue_dict(known) if known else None,
            reasons=reasons,
            flags=flags,
        )

    # Fallthrough
    reasons.append("tier1:clarify_other")
    return RouterResult(
        language=language,
        intent=intent,
        tier=1,
        stage="clarify",
        known_issue_id=known.issue_id if known else None,
        known_issue=_issue_dict(known) if known else None,
        reasons=reasons,
        flags=flags,
    )


def _pick_tier2_stage(
    intent: str,
    known: Optional[KnownIssue],
    signals: Dict[str, bool],
    reasons: List[str],
) -> str:
    if known and (known.confidence or "").lower() == "high":
        action = resolve_skip_action(known)
        if action and action != "none":
            reasons.append(f"known_issue_high:{known.issue_id}:{action}")
            if action == "none":
                return "wifi_guide"
            return action
        if known.issue_id == "wifi_timeout":
            reasons.append("known_issue:wifi_guide")
            return "wifi_guide"

    if known and (known.confidence or "").lower() == "medium":
        action = resolve_skip_action(known)
        if action in {"request_video", "request_photo"} and not signals.get("prior_troubleshooting"):
            # Still clarify/troubleshoot first for medium unless fail already confirmed
            if not signals.get("buyer_confirms_failed"):
                reasons.append("medium_issue_first_troubleshoot")
                return "clarify_or_troubleshoot"
        if action and action != "none":
            reasons.append(f"known_issue_medium:{known.issue_id}:{action}")
            return action

    if intent == "not_arrived":
        reasons.append("stage:courier_chase")
        return "courier_chase"

    if not signals.get("prior_troubleshooting"):
        reasons.append("stage:clarify_or_troubleshoot")
        return "clarify_or_troubleshoot"

    if signals.get("buyer_confirms_failed"):
        reasons.append("stage:request_video")
        return "request_video"

    if signals.get("video_received") or signals.get("evidence_obvious"):
        # Prefer refund unless known high replace
        if known and resolve_skip_action(known) == "resolve_replace":
            reasons.append("stage:resolve_replace")
            return "resolve_replace"
        reasons.append("stage:resolve_refund")
        return "resolve_refund"

    reasons.append("stage:clarify_or_troubleshoot_fallback")
    return "clarify_or_troubleshoot"


def _issue_dict(issue: Optional[KnownIssue]) -> Optional[Dict[str, Any]]:
    if not issue:
        return None
    return {
        "issue_id": issue.issue_id,
        "diagnosis": issue.diagnosis,
        "confidence": issue.confidence,
        "skip_to_action": resolve_skip_action(issue),
        "raw_skip_to_action": issue.skip_to_action,
        "evidence_required": issue.evidence_required,
        "disposal_note": issue.disposal_note,
        "batch_safe": issue.batch_safe,
    }


async def load_active_known_issues(db: AsyncSession) -> List[KnownIssue]:
    result = await db.execute(select(KnownIssue).where(KnownIssue.active == True))  # noqa: E712
    return list(result.scalars().all())


def latest_buyer_message(messages: Sequence[Message]) -> Optional[Message]:
    buyers = [m for m in messages if (m.sender_type or "").lower() == "buyer"]
    return buyers[-1] if buyers else None


async def run_router(
    db: AsyncSession,
    *,
    thread: MessageThread,
    messages: Sequence[Message],
    skus: Sequence[str],
    order_date: Optional[datetime] = None,
) -> RouterResult:
    msgs = sorted(messages, key=lambda m: m.ebay_created_at or datetime.min)
    last_buyer = latest_buyer_message(msgs)
    text = (last_buyer.content or "") if last_buyer else ""
    # If no buyer message, use last message content
    if not text and msgs:
        text = msgs[-1].content or ""

    stored = (last_buyer.detected_language if last_buyer else None) or None
    language = detect_language(text, stored)
    intent = classify_intent(text)
    issues = await load_active_known_issues(db)
    known = match_known_issue(
        issues,
        text=text,
        skus=skus,
        has_image=_buyer_has_image(last_buyer),
    )
    signals = _thread_signals(msgs)
    oow = _out_of_warranty(order_date)
    ebay_case = _ebay_case_flag(text)
    return route(
        language=language,
        intent=intent,
        known=known,
        signals=signals,
        out_of_warranty=oow,
        ebay_case=ebay_case,
    )


def build_escalation_card(
    *,
    router: RouterResult,
    thread: MessageThread,
    messages: Sequence[Message],
) -> Dict[str, Any]:
    msgs = sorted(messages, key=lambda m: m.ebay_created_at or datetime.min)
    last_buyer = latest_buyer_message(msgs)
    preview = ((last_buyer.content or "")[:400] if last_buyer else "")
    suggested = None
    if router.reasons and any("seller_already_decided" in r for r in router.reasons):
        suggested = (
            "You already responded — review before overriding. "
            "Draft is blocked so the router cannot overturn your prior decision."
        )
    elif router.known_issue_id == "melted_plug" or router.stage == "request_photo":
        suggested = "Ask for a clear photo of the plug/socket and any damage before promising a fix."
    elif router.reasons and any("de_return" in r for r in router.reasons):
        suggested = "DE return — discuss reason/postage yourself; free-returns path does not apply."
    elif router.flags.get("ebay_case"):
        suggested = "eBay case / MGB language detected — handle carefully; no automated resolution draft."
    elif router.flags.get("out_of_warranty"):
        suggested = "Order appears out of warranty window — goodwill only if you choose."

    return {
        "tier": 3,
        "intent": router.intent,
        "language": router.language,
        "stage_hint": router.stage,
        "known_issue_id": router.known_issue_id,
        "known_issue": router.known_issue,
        "reasons": router.reasons,
        "flags": router.flags,
        "thread_id": thread.thread_id,
        "buyer_username": thread.buyer_username,
        "sku": thread.sku,
        "order_id": thread.ebay_order_id,
        "last_buyer_preview": preview,
        "suggested_next_step": suggested,
        "summary": (
            f"Tier 3 escalation — intent={router.intent}, lang={router.language}"
            + (f", known={router.known_issue_id}" if router.known_issue_id else "")
            + f". Reasons: {', '.join(router.reasons) or 'n/a'}."
        ),
    }


STYLE_PACK = _STYLE_PACK
PROMISE_UPDATE_PATTERNS = _PROMISE_UPDATE
