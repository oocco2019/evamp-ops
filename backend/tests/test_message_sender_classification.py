"""
Unit tests for member message sender classification (buyer vs seller).
Run from backend: pytest tests/test_message_sender_classification.py -v
"""
import pytest
from unittest.mock import patch

from app.api.messages import (
    _member_message_display_username,
    _member_message_sender_type,
    _sender_is_seller_account,
)


def test_sender_is_seller_account_matches_config_lower():
    assert _sender_is_seller_account("MyStore", "mystore") is True
    assert _sender_is_seller_account("other", "mystore") is False


@patch("app.api.messages.settings")
def test_sender_is_seller_evamp_prefix(mock_settings):
    mock_settings.EBAY_SELLER_USERNAME = ""
    assert _sender_is_seller_account("evamp_foo", "") is True


def test_infer_seller_when_sender_empty_recipient_is_buyer():
    """eBay may omit senderUsername on seller replies; recipient is then the buyer."""
    assert _member_message_sender_type(None, "boxstar170", "evamp_shop") == "seller"
    assert _member_message_sender_type("", "boxstar170", "evamp_shop") == "seller"


def test_infer_buyer_when_sender_empty_recipient_is_seller():
    """Message to the seller is from the buyer."""
    assert _member_message_sender_type(None, "evamp_shop", "evamp_shop") == "buyer"


def test_explicit_sender_still_used_when_present():
    assert _member_message_sender_type("evamp_shop", "boxstar170", "evamp_shop") == "seller"
    assert _member_message_sender_type("boxstar170", "evamp_shop", "evamp_shop") == "buyer"


def test_both_empty_defaults_buyer():
    assert _member_message_sender_type(None, None, "evamp_shop") == "buyer"


@patch("app.api.messages.settings")
def test_display_username_fills_seller_when_inferred(mock_settings):
    mock_settings.EBAY_SELLER_USERNAME = "evamp_shop"
    assert (
        _member_message_display_username("seller", "", "boxstar170") == "evamp_shop"
    )


@patch("app.api.messages.settings")
def test_display_username_fills_buyer_from_thread(mock_settings):
    mock_settings.EBAY_SELLER_USERNAME = "evamp_shop"
    assert (
        _member_message_display_username("buyer", "", "boxstar170") == "boxstar170"
    )
