from datetime import datetime
from types import SimpleNamespace

from app.api.messages import (
    _build_message_media_items_for_response,
    _message_sort_key,
    _update_existing_message_media,
)


def test_update_existing_message_media_preserves_metadata_on_empty_refresh():
    existing = SimpleNamespace(
        media=[
            {
                "mediaName": "proof.jpg",
                "mediaType": "IMAGE",
                "mediaUrl": "https://i.ebayimg.com/images/example/s-l1600.jpg",
            }
        ]
    )

    _update_existing_message_media(existing, [])

    assert existing.media == [
        {
            "mediaName": "proof.jpg",
            "mediaType": "IMAGE",
            "mediaUrl": "https://i.ebayimg.com/images/example/s-l1600.jpg",
        }
    ]


def test_update_existing_message_media_accepts_non_empty_replacement():
    existing = SimpleNamespace(media=[{"mediaName": "old.jpg", "mediaType": "IMAGE"}])
    incoming = [{"mediaName": "new.pdf", "mediaType": "PDF", "mediaUrl": "https://example.com/new.pdf"}]

    _update_existing_message_media(existing, incoming)

    assert existing.media == incoming


def test_build_message_media_items_uses_stored_blob_when_json_metadata_missing():
    message = SimpleNamespace(message_id="msg-1", media=None)
    blob = SimpleNamespace(
        message_id="msg-1",
        media_index=0,
        media_name="stored.jpg",
        media_type="IMAGE",
    )

    media = _build_message_media_items_for_response(message, {("msg-1", 0): blob})

    assert media is not None
    assert media[0].mediaName == "stored.jpg"
    assert media[0].mediaType == "IMAGE"
    assert media[0].mediaUrl == "/api/messages/media/msg-1/0"


def test_message_sort_key_handles_null_ebay_created_at():
    assert _message_sort_key(SimpleNamespace(ebay_created_at=None)) == datetime.min.replace(tzinfo=None)
