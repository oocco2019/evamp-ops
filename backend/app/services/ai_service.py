"""
Main AI service with provider abstraction
"""
from typing import Dict, Any, Optional, List

import httpx
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.models.settings import AIModelSetting, APICredential
from app.core.security import encryption_service
from app.services.ai_providers import AIProvider, AnthropicProvider, OpenAIProvider


# Simple in-process cache for the live model list so we don't hit the
# provider on every settings page load. TTL in seconds.
_MODEL_LIST_CACHE: Dict[str, Any] = {}
_MODEL_LIST_TTL = 3600  # 1 hour


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

        self._provider = await self._provider_from_setting(model_setting)
        return self._provider

    async def get_provider_for_model_id(self, model_id: int) -> AIProvider:
        """Build a provider for a specific AIModelSetting id (does not change default cache)."""
        result = await self.db.execute(
            select(AIModelSetting).where(AIModelSetting.id == model_id)
        )
        model_setting = result.scalar_one_or_none()
        if not model_setting:
            raise ValueError(f"AI model id {model_id} not found.")
        return await self._provider_from_setting(model_setting)

    async def get_provider_for_provider_model(
        self, provider_name: str, model_name: str
    ) -> AIProvider:
        """
        Build a provider from Misc API credentials + a live catalog model id.
        Used by Messages-Test model picker (no need to save the model first).
        """
        provider_name = (provider_name or "").strip().lower()
        model_name = (model_name or "").strip()
        if not provider_name or not model_name:
            raise ValueError("provider and model_name are required.")
        if provider_name not in ("anthropic", "openai"):
            raise ValueError(f"Unsupported provider '{provider_name}'. Use anthropic or openai.")

        api_key = await self._get_provider_api_key(provider_name)
        if not api_key:
            raise ValueError(
                f"No API key found for provider '{provider_name}'. "
                f"Add it in Misc → API."
            )

        # Reuse temperature/max_tokens from default row for that provider when present.
        result = await self.db.execute(
            select(AIModelSetting)
            .where(AIModelSetting.provider == provider_name)
            .order_by(AIModelSetting.is_default.desc(), AIModelSetting.id)
            .limit(1)
        )
        hint = result.scalar_one_or_none()
        temperature = hint.temperature if hint and hint.temperature is not None else 0.7
        max_tokens = hint.max_tokens if hint and hint.max_tokens is not None else 2000
        system_override = hint.system_prompt_override if hint else None

        if provider_name == "anthropic":
            retired_anthropic = {
                "claude-3-5-sonnet-20241022": "claude-sonnet-5",
                "claude-3-5-sonnet-20240620": "claude-sonnet-5",
                "claude-3-opus-20240229": "claude-opus-5",
                "claude-3-7-sonnet-20250219": "claude-sonnet-5",
                "claude-3-5-haiku-20241022": "claude-haiku-4-5-20251001",
                "claude-3-haiku-20240307": "claude-haiku-4-5-20251001",
                "claude-sonnet-4-5-20250929": "claude-sonnet-5",
                "claude-opus-4-5-20251101": "claude-opus-5",
            }
            model_name = retired_anthropic.get(model_name, model_name)

        return self._create_provider(
            provider_name=provider_name,
            api_key=api_key,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt_override=system_override,
        )

    async def _provider_from_setting(self, model_setting: AIModelSetting) -> AIProvider:
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

        # Map retired Anthropic model IDs to current replacements (API returns error for retired models).
        # Destinations use undated aliases where possible so Anthropic rolls the snapshot
        # forward automatically; aliases do NOT cross generations, so bump these on major upgrades.
        model_name = model_setting.model_name
        if model_setting.provider.lower() == "anthropic":
            retired_anthropic = {
                "claude-3-5-sonnet-20241022": "claude-sonnet-5",
                "claude-3-5-sonnet-20240620": "claude-sonnet-5",
                "claude-3-opus-20240229": "claude-opus-5",
                "claude-3-7-sonnet-20250219": "claude-sonnet-5",
                "claude-3-5-haiku-20241022": "claude-haiku-4-5-20251001",
                "claude-3-haiku-20240307": "claude-haiku-4-5-20251001",
                # Previous-generation 4.x snapshots now retired / superseded:
                "claude-sonnet-4-5-20250929": "claude-sonnet-5",
                "claude-opus-4-5-20251101": "claude-opus-5",
                "claude-haiku-4-5-20251001": "claude-haiku-4-5-20251001",
            }
            model_name = retired_anthropic.get(model_name, model_name)

        return self._create_provider(
            provider_name=model_setting.provider,
            api_key=api_key,
            model_name=model_name,
            temperature=temperature,
            max_tokens=max_tokens,
            system_prompt_override=model_setting.system_prompt_override
        )

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

    async def _get_provider_api_key(self, provider: str) -> Optional[str]:
        """
        Fetch and decrypt the active API key for a given provider, or None if absent.
        """
        result = await self.db.execute(
            select(APICredential).where(
                APICredential.service_name == provider,
                APICredential.key_name == "api_key",
                APICredential.is_active == True
            )
        )
        credential = result.scalar_one_or_none()
        if not credential:
            return None
        return encryption_service.decrypt(credential.encrypted_value)

    async def list_available_models(
        self,
        provider: str,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Return the list of models currently available for a provider, fetched live
        from the provider's API so the Settings dropdown stays current without code
        changes. Falls back to a cached copy on transient failure.

        Args:
            provider: "anthropic" or "openai"
            use_cache: Serve from the in-process cache if a fresh entry exists

        Returns:
            List of dicts, each with at least "id" and "display_name".
        """
        import time

        provider = provider.lower()
        now = time.time()

        cache_entry = _MODEL_LIST_CACHE.get(provider)
        if use_cache and cache_entry and (now - cache_entry["ts"]) < _MODEL_LIST_TTL:
            return cache_entry["models"]

        api_key = await self._get_provider_api_key(provider)
        if not api_key:
            # No key -> return whatever we last cached (possibly empty), don't raise:
            # the settings page should still render.
            return cache_entry["models"] if cache_entry else []

        try:
            if provider == "anthropic":
                models = await self._fetch_anthropic_models(api_key)
            elif provider == "openai":
                models = await self._fetch_openai_models(api_key)
            else:
                models = []
        except Exception:
            # On any network/parse failure, serve stale cache rather than breaking the page.
            return cache_entry["models"] if cache_entry else []

        _MODEL_LIST_CACHE[provider] = {"ts": now, "models": models}
        return models

    @staticmethod
    async def _fetch_anthropic_models(api_key: str) -> List[Dict[str, Any]]:
        """
        GET https://api.anthropic.com/v1/models
        Returns items with id, display_name, and a capabilities object.
        """
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                },
                params={"limit": 100},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])

        return [
            {
                "id": m["id"],
                "display_name": m.get("display_name", m["id"]),
            }
            for m in data
        ]

    @staticmethod
    async def _fetch_openai_models(api_key: str) -> List[Dict[str, Any]]:
        """
        GET https://api.openai.com/v1/models
        OpenAI returns every model on the account (embeddings, tts, etc.), so filter
        to chat-capable "gpt-" families for a usable dropdown.
        """
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.openai.com/v1/models",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            data = resp.json().get("data", [])

        models = [
            {"id": m["id"], "display_name": m["id"]}
            for m in data
            if m.get("id", "").startswith("gpt-")
        ]
        models.sort(key=lambda m: m["id"], reverse=True)
        return models

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

    async def complete(
        self,
        user_prompt: str,
        *,
        system: str,
        max_tokens: int = 4000,
        temperature: float = 0,
    ) -> str:
        """
        Raw LLM completion (not a CS draft). Used for AI message search and similar tasks.
        """
        provider = await self.get_active_provider()
        return await provider.complete(
            user_prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )

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