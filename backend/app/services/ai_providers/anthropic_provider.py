"""
Anthropic Claude AI provider implementation
"""
from typing import Dict, Any
from anthropic import AsyncAnthropic
from app.services.ai_providers.base import AIProvider


class AnthropicProvider(AIProvider):
    """Implementation for Anthropic Claude models"""
    
    def __init__(self, api_key: str, model_name: str, **kwargs):
        super().__init__(api_key, model_name, **kwargs)
        self.client = AsyncAnthropic(api_key=api_key)
    
    async def generate_message(
        self, 
        prompt: str, 
        context: Dict[str, Any]
    ) -> str:
        """
        Generate a customer service message using Claude.
        
        Context keys:
            - thread_history: List of previous messages
            - global_instructions: Global AI instructions
            - sku_instructions: SKU-specific instructions
            - knowledge_base: Relevant past conversations
        """
        # Build system prompt
        system_prompt = self.system_prompt_override or self._build_system_prompt(context)
        
        # Build user message with context
        user_message = self._build_user_message(prompt, context)
        
        # Call Claude API
        response = await self.client.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            system=system_prompt,
            messages=[
                {"role": "user", "content": user_message}
            ]
        )
        
        return response.content[0].text
    
    async def detect_language(self, text: str) -> str:
        """Detect language using Claude"""
        response = await self.client.messages.create(
            model=self.model_name,
            max_tokens=10,
            temperature=0,
            messages=[{
                "role": "user",
                "content": f"What is the ISO 639-1 language code of this text? "
                          f"Respond with ONLY the 2-letter code, nothing else.\n\nText: {text[:500]}"
            }]
        )
        
        return response.content[0].text.strip().lower()[:2]
    
    async def translate(
        self, 
        text: str, 
        source_lang: str,
        target_lang: str
    ) -> Dict[str, str]:
        """Translate text with back-translation for verification"""
        # Forward translation
        forward_response = await self.client.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            temperature=0.3,
            messages=[{
                "role": "user",
                "content": f"Translate the following text from {source_lang} to {target_lang}. "
                          f"Preserve URLs, order IDs, and technical terms unchanged. "
                          f"Return ONLY the translated text, no explanations.\n\n{text}"
            }]
        )
        translated = forward_response.content[0].text
        
        # Back translation for verification
        back_response = await self.client.messages.create(
            model=self.model_name,
            max_tokens=self.max_tokens,
            temperature=0.3,
            messages=[{
                "role": "user",
                "content": f"Translate the following text from {target_lang} to {source_lang}. "
                          f"Return ONLY the translated text, no explanations.\n\n{translated}"
            }]
        )
        back_translated = back_response.content[0].text
        
        return {
            "translated": translated,
            "back_translated": back_translated
        }
    
    def _build_system_prompt(self, context: Dict[str, Any]) -> str:
        """Build system prompt from context"""
        parts = [
            "You are a professional customer service assistant for an eBay seller.",
            "Your goal is to provide helpful, accurate, and courteous responses.",
        ]
        
        # Add global instructions
        if context.get("global_instructions"):
            parts.append(f"\nGlobal Guidelines:\n{context['global_instructions']}")
        
        # Add SKU-specific instructions
        if context.get("sku_instructions"):
            parts.append(f"\nProduct-Specific Information:\n{context['sku_instructions']}")
        
        return "\n".join(parts)
    
    def _build_user_message(self, prompt: str, context: Dict[str, Any]) -> str:
        """Build user message with context"""
        parts = []
        
        # Add thread history
        if context.get("thread_history"):
            parts.append("Previous conversation:")
            for msg in context["thread_history"]:
                sender = msg.get("sender", "Unknown")
                content = msg.get("content", "")
                parts.append(f"{sender}: {content}")
            parts.append("")
        
        # Add knowledge base examples
        if context.get("knowledge_base"):
            parts.append("Relevant past interactions:")
            parts.append(context["knowledge_base"])
            parts.append("")
        
        # Add the actual prompt
        parts.append(prompt)
        
        return "\n".join(parts)
