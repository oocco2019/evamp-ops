"""
Main AI service with provider abstraction
"""
from typing import Dict, Any, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.settings import AIModelSetting, APICredential
from app.core.security import encryption_service
from app.services.ai_providers import AIProvider, AnthropicProvider, OpenAIProvider


class AIService:
    """
    Main AI service that manages multiple providers.
    Selects the active provider based on database settings.
    """
    
    def __init__(self, db: AsyncSession):
        self.db = db
        self._provider: Optional[AIProvider] = None
    
    async def get_active_provider(self) -> AIProvider:
        """
        Get the currently active AI provider based on settings.
        
        Returns:
            Configured AI provider instance
            
        Raises:
            ValueError: If no default model is configured or API key is missing
        """
        if self._provider:
            return self._provider
        
        # Get default AI model setting
        result = await self.db.execute(
            select(AIModelSetting).where(AIModelSetting.is_default == True)
        )
        model_setting = result.scalar_one_or_none()
        
        if not model_setting:
            raise ValueError(
                "No default AI model configured. "
                "Please configure an AI model in the Settings page."
            )
        
        # Get API key for the provider
        result = await self.db.execute(
            select(APICredential).where(
                APICredential.service_name == model_setting.provider,
                APICredential.key_name == "api_key",
                APICredential.is_active == True
            )
        )
        credential = result.scalar_one_or_none()
        
        if not credential:
            raise ValueError(
                f"No API key found for provider '{model_setting.provider}'. "
                f"Please add API credentials in the Settings page."
            )
        
        # Decrypt API key
        api_key = encryption_service.decrypt(credential.encrypted_value)
        
        # Normalize optional numeric fields so the SDK never gets None (avoids Pydantic/serialization errors)
        temperature = model_setting.temperature if model_setting.temperature is not None else 0.7
        max_tokens = model_setting.max_tokens if model_setting.max_tokens is not None else 2000
        
        # Map retired Anthropic model IDs to current replacements (API returns error for retired models)
        model_name = model_setting.model_name
        if model_setting.provider.lower() == "anthropic":
            retired_anthropic = {
                "claude-3-5-sonnet-20241022": "claude-sonnet-4-5-20250929",
                "claude-3-5-sonnet-20240620": "claude-sonnet-4-5-20250929",
                "claude-3-opus-20240229": "claude-opus-4-5-20251101",
                "claude-3-7-sonnet-20250219": "claude-sonnet-4-5-20250929",
                "claude-3-5-haiku-20241022": "claude-haiku-4-5-20251001",
            }
            model_name = retired_anthropic.get(model_name, model_name)
        
        # Create provider instance
        self._provider = self._create_provider(
            provider_name=model_setting.provider,
            api_key=api_key,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt_override=model_setting.system_prompt_override
        )
        
        return self._provider
    
    def _create_provider(
        self,
        provider_name: str,
        api_key: str,
        model_name: str,
        **kwargs
    ) -> AIProvider:
        """
        Factory method to create provider instances.
        
        Args:
            provider_name: "anthropic", "openai", or "litellm"
            api_key: API key for the provider
            model_name: Model to use
            **kwargs: Additional configuration
            
        Returns:
            AI provider instance
        """
        providers = {
            "anthropic": AnthropicProvider,
            "openai": OpenAIProvider,
            # TODO: Add LiteLLM provider when needed
        }
        
        provider_class = providers.get(provider_name.lower())
        if not provider_class:
            raise ValueError(
                f"Unknown provider '{provider_name}'. "
                f"Supported: {', '.join(providers.keys())}"
            )
        
        return provider_class(api_key=api_key, model_name=model_name, **kwargs)
    
    async def generate_message(
        self, 
        prompt: str, 
        context: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Generate a customer service message.
        
        Args:
            prompt: The main prompt/instruction
            context: Additional context (thread history, instructions, etc.)
            
        Returns:
            Generated message text
        """
        provider = await self.get_active_provider()
        return await provider.generate_message(prompt, context or {})
    
    async def detect_language(self, text: str) -> str:
        """
        Detect the language of a text.
        
        Args:
            text: Text to analyze
            
        Returns:
            ISO 639-1 language code
        """
        provider = await self.get_active_provider()
        return await provider.detect_language(text)
    
    async def translate(
        self, 
        text: str, 
        source_lang: str,
        target_lang: str
    ) -> Dict[str, str]:
        """
        Translate text with back-translation.
        
        Args:
            text: Text to translate
            source_lang: Source language code
            target_lang: Target language code
            
        Returns:
            Dict with "translated" and "back_translated" keys
        """
        provider = await self.get_active_provider()
        return await provider.translate(text, source_lang, target_lang)
    
    def reset_provider(self):
        """Reset cached provider (call after settings change)"""
        self._provider = None


async def get_ai_service(db: AsyncSession) -> AIService:
    """Dependency for getting AI service"""
    return AIService(db)
