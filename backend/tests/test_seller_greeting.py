"""Greeting helpers used by legacy reply compose."""
from datetime import datetime
from types import SimpleNamespace

from app.services.reply_compose import message_opens_with_greeting, seller_greeted_today


def test_seller_greeted_today_blocks_rehello():
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
