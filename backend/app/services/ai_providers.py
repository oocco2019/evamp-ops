"""
AI Provider implementations for message drafting and translation.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import httpx


class AIProvider(ABC):
    """Abstract base class for AI providers."""
    
    def __init__(
        self,
        api_key: str,
        model_name: str,
        temperature: float = 0.7,
        max_tokens: int = 2000,
        system_prompt_override: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model_name = model_name
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.system_prompt_override = system_prompt_override
    
    @abstractmethod
    async def generate_message(self, prompt: str, context: Dict[str, Any]) -> str:
        """Generate a customer service message."""
        pass
    
    @abstractmethod
    async def detect_language(self, text: str) -> str:
        """Detect language of text, return ISO 639-1 code."""
        pass
    
    @abstractmethod
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> Dict[str, str]:
        """Translate text with back-translation verification."""
        pass


class AnthropicProvider(AIProvider):
    """Anthropic Claude provider."""
    
    API_URL = "https://api.anthropic.com/v1/messages"
    
    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build the system prompt from context."""
        if self.system_prompt_override:
            return self.system_prompt_override
        
        parts = [
            "You are a professional eBay seller customer service assistant.",
            "Your role is to draft helpful, polite, and professional responses to buyers.",
            "Keep responses concise but thorough. Be empathetic and solution-focused.",
        ]
        
        global_instructions = context.get("global_instructions", "")
        if global_instructions:
            parts.append(f"\n\nGlobal instructions from the seller:\n{global_instructions}")
        
        sku_instructions = context.get("sku_instructions", "")
        if sku_instructions:
            parts.append(f"\n\nProduct-specific instructions (SKU):\n{sku_instructions}")
        
        return "\n".join(parts)
    
    def _format_thread_history(self, thread_history: List[Dict[str, str]]) -> str:
        """Format thread history for the prompt."""
        if not thread_history:
            return "No previous messages."
        
        lines = []
        for msg in thread_history:
            role = "Buyer" if msg.get("role") == "buyer" else "Seller"
            content = msg.get("content", "").strip()
            lines.append(f"[{role}]: {content}")
        
        return "\n\n".join(lines)
    
    async def generate_message(self, prompt: str, context: Dict[str, Any]) -> str:
        """Generate a customer service message using Claude."""
        system = self._build_system_prompt(context)
        thread_history = context.get("thread_history", [])
        
        user_content = f"""Here is the conversation history:

{self._format_thread_history(thread_history)}

---

{prompt}

Draft a response to the buyer. Do not include any preamble or explanation - just provide the message text that should be sent to the buyer."""

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "system": system,
                    "messages": [{"role": "user", "content": user_content}],
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            
            # Extract text from response
            content = data.get("content", [])
            if content and len(content) > 0:
                return content[0].get("text", "").strip()
            return ""
    
    async def detect_language(self, text: str) -> str:
        """Detect language using Claude."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "max_tokens": 10,
                    "temperature": 0,
                    "messages": [{
                        "role": "user",
                        "content": f"Detect the language of this text and respond with only the ISO 639-1 two-letter code (e.g., 'en', 'de', 'fr'):\n\n{text[:500]}"
                    }],
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("content", [])
            if content and len(content) > 0:
                return content[0].get("text", "en").strip().lower()[:2]
            return "en"
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> Dict[str, str]:
        """Translate text with back-translation."""
        # Forward translation
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "max_tokens": self.max_tokens,
                    "temperature": 0.3,
                    "messages": [{
                        "role": "user",
                        "content": f"Translate the following text from {source_lang} to {target_lang}. Preserve the meaning and tone. Do not add any explanation - just provide the translation:\n\n{text}"
                    }],
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("content", [])
            translated = content[0].get("text", "").strip() if content else text
        
        # Back translation
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "max_tokens": self.max_tokens,
                    "temperature": 0.3,
                    "messages": [{
                        "role": "user",
                        "content": f"Translate the following text from {target_lang} back to {source_lang}. This is for verification. Do not add any explanation - just provide the translation:\n\n{translated}"
                    }],
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            content = data.get("content", [])
            back_translated = content[0].get("text", "").strip() if content else translated
        
        return {
            "translated": translated,
            "back_translated": back_translated,
        }


class OpenAIProvider(AIProvider):
    """OpenAI GPT provider."""
    
    API_URL = "https://api.openai.com/v1/chat/completions"
    
    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build the system prompt from context."""
        if self.system_prompt_override:
            return self.system_prompt_override
        
        parts = [
            "You are a professional eBay seller customer service assistant.",
            "Your role is to draft helpful, polite, and professional responses to buyers.",
            "Keep responses concise but thorough. Be empathetic and solution-focused.",
        ]
        
        global_instructions = context.get("global_instructions", "")
        if global_instructions:
            parts.append(f"\n\nGlobal instructions from the seller:\n{global_instructions}")
        
        sku_instructions = context.get("sku_instructions", "")
        if sku_instructions:
            parts.append(f"\n\nProduct-specific instructions (SKU):\n{sku_instructions}")
        
        return "\n".join(parts)
    
    def _format_thread_history(self, thread_history: List[Dict[str, str]]) -> str:
        """Format thread history for the prompt."""
        if not thread_history:
            return "No previous messages."
        
        lines = []
        for msg in thread_history:
            role = "Buyer" if msg.get("role") == "buyer" else "Seller"
            content = msg.get("content", "").strip()
            lines.append(f"[{role}]: {content}")
        
        return "\n\n".join(lines)
    
    async def generate_message(self, prompt: str, context: Dict[str, Any]) -> str:
        """Generate a customer service message using GPT."""
        system = self._build_system_prompt(context)
        thread_history = context.get("thread_history", [])
        
        user_content = f"""Here is the conversation history:

{self._format_thread_history(thread_history)}

---

{prompt}

Draft a response to the buyer. Do not include any preamble or explanation - just provide the message text that should be sent to the buyer."""

        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "max_tokens": self.max_tokens,
                    "temperature": self.temperature,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_content},
                    ],
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            
            choices = data.get("choices", [])
            if choices and len(choices) > 0:
                return choices[0].get("message", {}).get("content", "").strip()
            return ""
    
    async def detect_language(self, text: str) -> str:
        """Detect language using GPT."""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "max_tokens": 10,
                    "temperature": 0,
                    "messages": [{
                        "role": "user",
                        "content": f"Detect the language of this text and respond with only the ISO 639-1 two-letter code (e.g., 'en', 'de', 'fr'):\n\n{text[:500]}"
                    }],
                },
                timeout=30.0,
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            if choices and len(choices) > 0:
                return choices[0].get("message", {}).get("content", "en").strip().lower()[:2]
            return "en"
    
    async def translate(
        self,
        text: str,
        source_lang: str,
        target_lang: str,
    ) -> Dict[str, str]:
        """Translate text with back-translation."""
        # Forward translation
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "max_tokens": self.max_tokens,
                    "temperature": 0.3,
                    "messages": [{
                        "role": "user",
                        "content": f"Translate the following text from {source_lang} to {target_lang}. Preserve the meaning and tone. Do not add any explanation - just provide the translation:\n\n{text}"
                    }],
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            translated = choices[0].get("message", {}).get("content", "").strip() if choices else text
        
        # Back translation
        async with httpx.AsyncClient() as client:
            response = await client.post(
                self.API_URL,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model_name,
                    "max_tokens": self.max_tokens,
                    "temperature": 0.3,
                    "messages": [{
                        "role": "user",
                        "content": f"Translate the following text from {target_lang} back to {source_lang}. This is for verification. Do not add any explanation - just provide the translation:\n\n{translated}"
                    }],
                },
                timeout=60.0,
            )
            response.raise_for_status()
            data = response.json()
            choices = data.get("choices", [])
            back_translated = choices[0].get("message", {}).get("content", "").strip() if choices else translated
        
        return {
            "translated": translated,
            "back_translated": back_translated,
        }
