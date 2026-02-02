"""
Anthropic Claude AI provider implementation (httpx-based to avoid SDK/Pydantic serialization issues).
"""
from typing import Dict, Any, List
import httpx
from app.services.ai_providers.base import AIProvider


API_URL = "https://api.anthropic.com/v1/messages"


class AnthropicProvider(AIProvider):
    """Implementation for Anthropic Claude models using raw HTTP (no SDK)."""

    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build system prompt from context."""
        if self.system_prompt_override:
            return self.system_prompt_override
        parts = [
            "You are a professional eBay seller customer service assistant.",
            "Your role is to draft helpful, polite, and professional responses to buyers.",
            "Keep responses concise but thorough. Be empathetic and solution-focused.",
        ]
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

Draft a response to the buyer. Do not include any preamble or explanation - just provide the message text that should be sent to the buyer."""

        payload = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "temperature": float(self.temperature),
            "system": system,
            "messages": [{"role": "user", "content": user_content}],
        }
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
        content = data.get("content", [])
        if content and len(content) > 0:
            return (content[0].get("text") or "").strip()
        return ""

    async def detect_language(self, text: str) -> str:
        """Detect language using Claude."""
        payload = {
            "model": self.model_name,
            "max_tokens": 10,
            "temperature": 0,
            "messages": [{
                "role": "user",
                "content": f"Detect the language of this text and respond with only the ISO 639-1 two-letter code (e.g., 'en', 'de', 'fr'):\n\n{text[:500]}",
            }],
        }
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
        content = data.get("content", [])
        if content and len(content) > 0:
            return (content[0].get("text", "en") or "en").strip().lower()[:2]
        return "en"

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
            "temperature": 0.3,
            "messages": [{
                "role": "user",
                "content": f"Translate the following text from {source_lang} to {target_lang}. Preserve the meaning and tone. Do not add any explanation - just provide the translation:\n\n{text}",
            }],
        }
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
        content = data.get("content", [])
        translated = content[0].get("text", "").strip() if content else text

        payload_back = {
            "model": self.model_name,
            "max_tokens": self.max_tokens,
            "temperature": 0.3,
            "messages": [{
                "role": "user",
                "content": f"Translate the following text from {target_lang} back to {source_lang}. This is for verification. Do not add any explanation - just provide the translation:\n\n{translated}",
            }],
        }
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
        content = data.get("content", [])
        back_translated = content[0].get("text", "").strip() if content else translated

        return {"translated": translated, "back_translated": back_translated}
