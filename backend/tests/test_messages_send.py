"""Tests for message send error handling."""
import httpx

from app.api.messages import _ebay_api_error_detail


def test_ebay_api_error_detail_from_errors_array():
    response = httpx.Response(
        400,
        json={
            "errors": [
                {
                    "errorId": 123,
                    "message": "Short",
                    "longMessage": "Contact details are not allowed in this message.",
                }
            ]
        },
    )
    assert _ebay_api_error_detail(response) == "Contact details are not allowed in this message."


def test_ebay_api_error_detail_fallback_to_text():
    response = httpx.Response(502, text="Bad Gateway")
    assert _ebay_api_error_detail(response) == "Bad Gateway"
