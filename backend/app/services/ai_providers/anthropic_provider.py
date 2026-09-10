"""
Anthropic Claude AI provider implementation (httpx-based to avoid SDK/Pydantic serialization issues).
"""
from typing import Dict, Any, List
import httpx
from app.services.ai_providers.base import AIProvider


API_URL = "https://api.anthropic.com/v1/messages"


def _rejects_temperature(model_name: str) -> bool:
    """
    Claude Opus 4.7 and later (including Sonnet 5, Opus 5, Fable 5, Mythos) reject
    `temperature` (and top_p/top_k): a non-default value returns a 400 error.
    For those models we omit the parameter entirely. Older models still accept it.
    """
    name = (model_name or "").lower()
    if any(tag in name for tag in ("-5", "sonnet-5", "opus-5", "fable-5", "mythos")):
        # Guard against matching "4-5" (4.5 generation) which still accepts temperature.
        if "4-5" not in name:
            return True
    if "opus-4-7" in name or "opus-4-8" in name:
        return True
    return False


def _extract_text(data: Dict[str, Any], default: str = "") -> str:
    """
    Pull the assistant's text from a Messages API response.

    Newer models (Sonnet 5, Opus 5, Fable 5) have thinking on by default, so the
    `content` array can start with a `thinking` block. Scan for the first block whose
    type is "text" rather than assuming content[0] is the text, otherwise the draft
    comes back empty.
    """
    content = data.get("content") or []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return (block.get("text") or "").strip()
    # Fallback: some responses may omit an explicit type but still carry text.
    for block in content:
        if isinstance(block, dict) and block.get("text"):
            return (block.get("text") or "").strip()
    return default


class AnthropicProvider(AIProvider):
    """Implementation for Anthropic Claude models using raw HTTP (no SDK)."""

    def _apply_temperature(self, payload: Dict[str, Any], temperature: float) -> Dict[str, Any]:
        """Add temperature to the payload only for models that accept it."""
        if not _rejects_temperature(self.model_name):
            payload["temperature"] = float(temperature)
        return payload

    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build system prompt from context."""
        if self.system_prompt_override:
            return self.system_prompt_override
        parts = [
            "You are a professional eBay seller customer service assistant.",
            "Your role is to draft helpful, polite, and professional responses to buyers.",
            "ALWAYS draft in English only, even when the buyer wrote in German or another language. "
            "Outbound German is handled separately by the seller.",
            "EMPATHY REGISTER (hard): When acknowledging a problem, connect via stress or hassle, not safety or wellbeing. "
            "'Sorry for the hassle' or 'I hope this didn't stress you too much' is the right level. "
            "Never write 'glad you're safe', 'I was worried', or anything implying family-level concern. "
            "PUNCTUATION (hard): Write like a normal text message. "
            "Never use em dashes, en dashes, or a spaced hyphen as a pause. "
            "Never write ', and' (no comma before and). Use a full stop or a short new sentence instead of dashes.",
            "Keep responses concise but thorough. Be empathetic and solution-focused.",
            "Do not invent timelines, refunds, or facts not supported by the thread or playbook.",
            "Read the full conversation; do not re-ask questions the buyer already answered.",
        ]
        policies = context.get("policies") or []
        if policies:
            parts.append("\n\nREPLY POLICIES (must follow):")
            for i, p in enumerate(policies, 1):
                body = p.get("body") if isinstance(p, dict) else str(p)
                parts.append(f"{i}. {body}")
        playbook = context.get("playbook_entries") or []
        if playbook:
            parts.append("\n\nPLAYBOOK ENTRIES (use when relevant):")
            for i, e in enumerate(playbook, 1):
                if isinstance(e, dict):
                    sym = (e.get("symptom") or "").strip()
                    res = (e.get("resolution") or "").strip()
                    line = f"{i}. {res}" if not sym else f"{i}. Symptom: {sym} -> {res}"
                else:
                    line = f"{i}. {e}"
                parts.append(line)
        product = (context.get("product_context") or "").strip()
        if product:
            parts.append(f"\n\nPRODUCT CONTEXT:\n{product}")
        samples = (context.get("sample_conversations") or "").strip()
        if samples:
            parts.append(
                "\n\nSAMPLE CONVERSATIONS (match tone, pacing, and how the seller leads. "
                "Do not copy tracking numbers, names, or exact wording unless it fits):\n"
                f"{samples}"
            )
        # Legacy fallbacks
        if context.get("global_instructions"):
            parts.append(f"\n\nGlobal instructions from the seller:\n{context['global_instructions']}")
        if context.get("sku_instructions"):
            parts.append(f"\n\nProduct-specific instructions (SKU):\n{context['sku_instructions']}")
        return "\n".join(parts)

    def _format_thread_history(self, thread_history: List[Dict[str, Any]]) -> str:
        """Format thread history for the prompt (expects 'role' and 'content' keys)."""
        if not thread_history:
            return "No previous messages."
        lines = []
        for msg in thread_history:
            role = "Buyer" if msg.get("role") == "buyer" else "Seller"
            content = (msg.get("content") or "").strip()
            lines.append(f"[{role}]: {content}")
        return "\n\n".join(lines)

    async def generate_message(self, prompt: str, context: Dict[str, Any]) -> str:
        """Generate a customer service message using Claude via REST API."""
        system = self._build_system_prompt(context)
        thread_history = context.get("thread_history", [])
        user_content = f"""Here is the conversation history:

{self._format_thread_history(thread_history)}

---

{prompt}

Draft a response to the buyer in English only. Do not write German or any other language. Do not include any preamble or explanation - just provide the message text."""

        payload = {
            "model": self.model_name,
            "max_tokens": int(context.get("max_tokens") or self.max_tokens),
            "system": system,
            "messages": [{"role": "user", "content": user_content}],
        }
        self._apply_temperature(payload, self.temperature)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
        return _extract_text(data, default="")

    async def complete(
        self,
        user_prompt: str,
        *,
        system: str,
        max_tokens: int = 2000,
        temperature: float = 0,
    ) -> str:
        """Raw Messages API call without CS-draft wrapping."""
        payload: Dict[str, Any] = {
            "model": self.model_name,
            "max_tokens": int(max_tokens),
            "system": system,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        self._apply_temperature(payload, temperature)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=180.0,
            )
            response.raise_for_status()
            data = response.json()
        return _extract_text(data, default="")

    async def detect_language(self, text: str) -> str:
        """Detect language using Claude."""
        payload = {
            "model": self.model_name,
            "max_tokens": 10,
            "messages": [{
                "role": "user",
                "content": f"Detect the language of this text and respond with only the ISO 639-1 two-letter code (e.g., 'en', 'de', 'fr'):\n\n{text[:500]}",
            }],
        }
        self._apply_temperature(payload, 0)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
        code = _extract_text(data, default="en")
        return (code or "en").strip().lower()[:2]

    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> Dict[str, str]:
        """Translate text with back-translation for verification."""
        payload_fwd = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "messages": [{
                "role": "user",
                "content": f"Translate the following text from {source_lang} to {target_lang}. Preserve the meaning and tone. Do not add any explanation - just provide the translation:\n\n{text}",
            }],
        }
        self._apply_temperature(payload_fwd, 0.3)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload_fwd,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
        translated = _extract_text(data, default=text)

        payload_back = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "messages": [{
                "role": "user",
                "content": f"Translate the following text from {target_lang} back to {source_lang}. This is for verification. Do not add any explanation - just provide the translation:\n\n{translated}",
            }],
        }
        self._apply_temperature(payload_back, 0.3)
        async with httpx.AsyncClient() as client:
            response = await client.post(
                API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload_back,
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
        back_translated = _extract_text(data, default=translated)

        return {"translated": translated, "back_translated": back_translated}