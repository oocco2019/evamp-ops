import asyncio

from app.services import ebay_client


def test_fetch_all_conversation_messages_follows_next_when_total_missing(monkeypatch):
    calls = []

    async def fake_fetch_page(access_token, conversation_id, conversation_type="FROM_MEMBERS", limit=50, offset=0):
        calls.append(offset)
        if offset == 0:
            return {
                "messages": [{"messageId": "m1"}],
                "next": "https://api.ebay.test/conversation/c1?offset=50",
            }
        return {"messages": [{"messageId": "m2"}]}

    monkeypatch.setattr(ebay_client, "fetch_conversation_messages_page", fake_fetch_page)

    messages = asyncio.run(ebay_client.fetch_all_conversation_messages("token", "c1"))

    assert [m["messageId"] for m in messages] == ["m1", "m2"]
    assert calls == [0, 50]
