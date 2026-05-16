from types import SimpleNamespace

from app.api.messages import _normalize_message_media, _update_existing_message_media


def test_existing_message_media_is_preserved_when_resync_omits_media():
    existing_media = [
        {
            "mediaName": "proof.jpg",
            "mediaType": "IMAGE",
            "mediaUrl": "https://i.ebayimg.com/images/example/s-l1600.jpg",
        }
    ]
    existing = SimpleNamespace(media=existing_media.copy())

    _update_existing_message_media(existing, _normalize_message_media([]))

    assert existing.media == existing_media


def test_existing_message_media_is_replaced_when_resync_provides_media():
    existing = SimpleNamespace(media=[{"mediaName": "old.jpg", "mediaType": "IMAGE", "mediaUrl": "https://old.example"}])
    replacement = _normalize_message_media(
        [{"mediaName": "new.pdf", "mediaType": "PDF", "mediaUrl": "https://example.com/new.pdf"}]
    )

    _update_existing_message_media(existing, replacement)

    assert existing.media == replacement
