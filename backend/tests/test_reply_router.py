"""Unit tests for CS rule router."""
from types import SimpleNamespace

from app.services.reply_router import (
    classify_intent,
    detect_language,
    match_known_issue,
    resolve_skip_action,
    route,
)


def test_detect_language_de_diacritic():
    assert detect_language("Hallo, das Gerät lädt nicht") == "DE"


def test_detect_language_en():
    assert detect_language("Hello, the cable will not charge my car") == "EN"


def test_classify_intent_priority_safety_over_charging():
    assert classify_intent("the plug melted and it won't charge") == "safety_claim"


def test_classify_intent_no_greedy_error():
    # "error" alone must not force not_charging
    assert classify_intent("I got an error code on Klarna checkout") == "cancel"


def test_de_return_tier3():
    r = route(
        language="DE",
        intent="return_request",
        known=None,
        signals={},
        out_of_warranty=False,
        ebay_case=False,
    )
    assert r.tier == 3
    assert any("de_return" in x for x in r.reasons)


def test_en_return_arrange():
    r = route(
        language="EN",
        intent="return_request",
        known=None,
        signals={},
        out_of_warranty=False,
        ebay_case=False,
    )
    assert r.tier == 2
    assert r.stage == "arrange_return"


def test_white_glue_batch_safe_false_refunds():
    issue = SimpleNamespace(
        issue_id="white_glue_cover",
        skip_to_action="resolve_replace",
        batch_safe=False,
        diagnosis="cover",
        confidence="high",
        evidence_required="photo",
        disposal_note=True,
        symptom_keywords=["cover off"],
        applies_to_sku="*",
        active=True,
        requires_image=False,
    )
    assert resolve_skip_action(issue) == "resolve_refund"
    r = route(
        language="EN",
        intent="physical_fault",
        known=issue,
        signals={"prior_troubleshooting": False},
        out_of_warranty=False,
        ebay_case=False,
    )
    assert r.tier == 2
    assert r.stage == "resolve_refund"


def test_melted_plug_routes_to_safety_stage_draft():
    issue = SimpleNamespace(
        issue_id="melted_plug",
        skip_to_action="request_photo",
        batch_safe=False,
        diagnosis="melt",
        confidence="medium",
        evidence_required="photo",
        disposal_note=False,
        symptom_keywords=["melted"],
        applies_to_sku="*",
        active=True,
        requires_image=False,
    )
    r = route(
        language="EN",
        intent="physical_fault",
        known=issue,
        signals={},
        out_of_warranty=False,
        ebay_case=False,
    )
    assert r.tier == 2
    assert r.stage == "safety"


def test_reassurance_claim_routes_to_reassurance_stage_draft():
    r = route(
        language="EN",
        intent="reassurance_claim",
        known=None,
        signals={},
        out_of_warranty=False,
        ebay_case=False,
    )
    assert r.tier == 2
    assert r.stage == "reassurance"


def test_match_known_issue_keywords():
    issue = SimpleNamespace(
        issue_id="wifi_timeout",
        symptom_keywords=["app timeout", "wlan"],
        applies_to_sku="*",
        active=True,
        requires_image=False,
        diagnosis="x",
        confidence="high",
        skip_to_action="none",
        evidence_required="none",
        disposal_note=False,
        batch_safe=False,
    )
    assert match_known_issue([issue], text="App timeout on WLAN", skus=["uke01"], has_image=False)
    assert (
        match_known_issue([issue], text="hello there", skus=["uke01"], has_image=False) is None
    )


def test_seller_decision_hold_line_tier3():
    """Seller denied; buyer brings nothing new → Tier 3 (do not arrange return)."""
    r = route(
        language="EN",
        intent="return_request",
        known=None,
        signals={
            "seller_already_decided": True,
            "buyer_new_material_info": False,
        },
        out_of_warranty=False,
        ebay_case=False,
    )
    assert r.tier == 3
    assert any("seller_already_decided" in x for x in r.reasons)


def test_seller_decision_new_material_still_drafts():
    """Seller denied; buyer then sends new evidence → normal EN return path."""
    r = route(
        language="EN",
        intent="return_request",
        known=None,
        signals={
            "seller_already_decided": True,
            "buyer_new_material_info": True,
        },
        out_of_warranty=False,
        ebay_case=False,
    )
    assert r.tier == 2
    assert r.stage == "arrange_return"


def test_seller_already_decided_detector():
    from datetime import datetime

    from app.services.reply_router import (
        buyer_new_material_after_decision,
        seller_already_decided,
    )

    t0 = datetime(2026, 1, 1, 12, 0, 0)
    t1 = datetime(2026, 1, 1, 12, 5, 0)
    buyer = SimpleNamespace(
        sender_type="buyer",
        content="I need a warranty replacement please",
        ebay_created_at=t0,
        media=None,
    )
    seller = SimpleNamespace(
        sender_type="seller",
        content="Unfortunately this is out of warranty so I'm not able to offer a free replacement.",
        ebay_created_at=t1,
        media=None,
    )
    assert seller_already_decided([buyer, seller]) is True
    assert buyer_new_material_after_decision([buyer, seller]) is False


def test_buyer_new_material_after_decision():
    from datetime import datetime

    from app.services.reply_router import buyer_new_material_after_decision

    t0 = datetime(2026, 1, 1, 12, 0, 0)
    t1 = datetime(2026, 1, 1, 12, 5, 0)
    t2 = datetime(2026, 1, 1, 13, 0, 0)
    msgs = [
        SimpleNamespace(
            sender_type="buyer",
            content="Warranty replacement please",
            ebay_created_at=t0,
            media=None,
        ),
        SimpleNamespace(
            sender_type="seller",
            content="Unfortunately we have to decline — past the warranty period.",
            ebay_created_at=t1,
            media=None,
        ),
        SimpleNamespace(
            sender_type="buyer",
            content="Here is a photo and my order number 12-34567-89012 purchased on 15/03/2025",
            ebay_created_at=t2,
            media=[{"url": "x"}],
        ),
    ]
    assert buyer_new_material_after_decision(msgs) is True


def test_seller_greeted_today_blocks_rehello():
    from datetime import datetime

    from app.services.reply_router import message_opens_with_greeting, seller_greeted_today

    assert message_opens_with_greeting("Hello,\n\nThanks for your message.")
    assert message_opens_with_greeting("Hi there — thanks for waiting.")
    assert not message_opens_with_greeting("Thanks for the update.")

    now = datetime(2026, 7, 28, 15, 0, 0)
    msgs = [
        SimpleNamespace(
            sender_type="seller",
            content="Hello,\n\nSorry to hear that.",
            subject="",
            ebay_created_at=datetime(2026, 7, 28, 9, 0, 0),
        ),
        SimpleNamespace(
            sender_type="buyer",
            content="Still not working",
            subject="",
            ebay_created_at=datetime(2026, 7, 28, 14, 0, 0),
        ),
    ]
    assert seller_greeted_today(msgs, now=now) is True
    # Different day → ok to greet again
    assert (
        seller_greeted_today(
            [
                SimpleNamespace(
                    sender_type="seller",
                    content="Hello,\n\nThanks.",
                    subject="",
                    ebay_created_at=datetime(2026, 7, 27, 9, 0, 0),
                )
            ],
            now=now,
        )
        is False
    )
