"""Claude 5 request flags: omit temperature, disable adaptive thinking."""
import asyncio
from unittest.mock import patch

import pytest

from app.services.ai_providers.anthropic_provider import (
    AnthropicProvider,
    _adaptive_thinking_on_by_default,
    _extract_text,
    _rejects_temperature,
)


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-5", True),
        ("claude-opus-5", True),
        ("claude-fable-5", True),
        ("claude-sonnet-5-20260901", True),
        ("claude-haiku-4-5-20251001", False),
        ("claude-sonnet-4-5-20250929", False),
        ("claude-3-5-sonnet-20241022", False),
        ("claude-opus-4-7", False),
        ("gpt-4", False),
        ("", False),
    ],
)
def test_adaptive_thinking_on_by_default(model, expected):
    assert _adaptive_thinking_on_by_default(model) is expected


@pytest.mark.parametrize(
    "model,expected",
    [
        ("claude-sonnet-5", True),
        ("claude-opus-5", True),
        ("claude-haiku-4-5-20251001", False),
        ("claude-opus-4-7", True),
        ("claude-3-5-sonnet-20241022", True),
    ],
)
def test_rejects_temperature(model, expected):
    assert _rejects_temperature(model) is expected


def test_extract_text_skips_thinking_block():
    data = {
        "content": [
            {"type": "thinking", "thinking": "plan the reply"},
            {"type": "text", "text": "Sorry for the hassle."},
        ],
        "stop_reason": "end_turn",
    }
    assert _extract_text(data) == "Sorry for the hassle."


def test_extract_text_thinking_only_is_empty():
    data = {
        "content": [{"type": "thinking", "thinking": "still reasoning"}],
        "stop_reason": "max_tokens",
    }
    assert _extract_text(data, default="") == ""


def test_sonnet_5_payload_disables_thinking_and_omits_temperature():
    p = AnthropicProvider(api_key="k", model_name="claude-sonnet-5")
    payload = {"model": p.model_name, "max_tokens": 700}
    p._finalize_payload(payload, 0.7)
    assert "temperature" not in payload
    assert payload["thinking"] == {"type": "disabled"}


def test_haiku_4_5_payload_keeps_temperature_without_thinking_field():
    p = AnthropicProvider(api_key="k", model_name="claude-haiku-4-5-20251001")
    payload = {"model": p.model_name, "max_tokens": 10}
    p._finalize_payload(payload, 0)
    assert payload["temperature"] == 0.0
    assert "thinking" not in payload


def test_opus_4_7_omits_temperature_without_thinking_field():
    p = AnthropicProvider(api_key="k", model_name="claude-opus-4-7")
    payload = {"model": p.model_name, "max_tokens": 700}
    p._finalize_payload(payload, 0.7)
    assert "temperature" not in payload
    assert "thinking" not in payload


class _FakeResp:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "content": [
                {"type": "thinking", "thinking": "unused"},
                {"type": "text", "text": "Thanks for waiting."},
            ]
        }


class _FakeClient:
    def __init__(self, captured):
        self.captured = captured

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def post(self, url, headers=None, json=None, timeout=None):
        self.captured["json"] = json
        return _FakeResp()


def test_generate_message_sends_thinking_disabled_for_sonnet_5():
    captured = {}
    p = AnthropicProvider(api_key="k", model_name="claude-sonnet-5", max_tokens=2000)

    async def _run():
        with patch(
            "app.services.ai_providers.anthropic_provider.httpx.AsyncClient",
            return_value=_FakeClient(captured),
        ):
            return await p.generate_message(
                "Draft a reply",
                {"max_tokens": 700, "thread_history": []},
            )

    out = asyncio.run(_run())
    assert out == "Thanks for waiting."
    body = captured["json"]
    assert body["max_tokens"] == 700
    assert body["thinking"] == {"type": "disabled"}
    assert "temperature" not in body


def test_detect_language_sends_thinking_disabled_for_sonnet_5():
    captured = {}

    class _LangResp(_FakeResp):
        def json(self):
            return {"content": [{"type": "text", "text": "de"}]}

    class _LangClient(_FakeClient):
        async def post(self, url, headers=None, json=None, timeout=None):
            self.captured["json"] = json
            return _LangResp()

    p = AnthropicProvider(api_key="k", model_name="claude-sonnet-5")

    async def _run():
        with patch(
            "app.services.ai_providers.anthropic_provider.httpx.AsyncClient",
            return_value=_LangClient(captured),
        ):
            return await p.detect_language("Guten Tag, wo ist meine Bestellung?")

    code = asyncio.run(_run())
    assert code == "de"
    assert captured["json"]["max_tokens"] == 10
    assert captured["json"]["thinking"] == {"type": "disabled"}
    assert "temperature" not in captured["json"]
