"""
Unit tests for global instruction from history (seller message detection).
Run from backend: pytest tests/ -v
"""
import pytest
from unittest.mock import patch

from app.services.global_instruction_from_history import _username_looks_like_seller


@patch("app.services.global_instruction_from_history.settings")
def test_username_evamp_prefix(mock_settings):
    mock_settings.EBAY_SELLER_USERNAME = ""
    assert _username_looks_like_seller("evamp_") is True
    assert _username_looks_like_seller("evamp_foo") is True
    assert _username_looks_like_seller("EVAMP_") is True


@patch("app.services.global_instruction_from_history.settings")
def test_username_evamp_contains(mock_settings):
    mock_settings.EBAY_SELLER_USERNAME = ""
    assert _username_looks_like_seller("evamp") is True
    assert _username_looks_like_seller("my_evamp_store") is True
    assert _username_looks_like_seller("  evamp  ") is True


@patch("app.services.global_instruction_from_history.settings")
def test_username_config_seller(mock_settings):
    mock_settings.EBAY_SELLER_USERNAME = "my_seller"
    assert _username_looks_like_seller("my_seller") is True
    assert _username_looks_like_seller("MY_SELLER") is True
    assert _username_looks_like_seller("evamp_") is True  # evamp still matches


@patch("app.services.global_instruction_from_history.settings")
def test_username_not_seller(mock_settings):
    mock_settings.EBAY_SELLER_USERNAME = ""
    assert _username_looks_like_seller("buyer123") is False
    assert _username_looks_like_seller("") is False
    assert _username_looks_like_seller(None) is False
    assert _username_looks_like_seller("  ") is False
