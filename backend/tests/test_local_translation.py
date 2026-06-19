"""Local translation helpers (langdetect + attachment stripping)."""

from app.services.local_translation import detect_language, strip_attachment_markers


def test_strip_attachment_markers():
    raw = "Hello [IMAGE: photo.jpg] world"
    assert strip_attachment_markers(raw) == "Hello world"


def test_detect_language_german():
    assert detect_language("Guten Tag, wo ist meine Bestellung?") == "de"


def test_detect_language_english():
    assert detect_language("Where is my order please?") == "en"


def test_detect_language_empty():
    assert detect_language("") == "en"
    assert detect_language("[IMAGE: x.jpg]") == "en"
