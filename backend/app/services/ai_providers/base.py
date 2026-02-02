"""
Base abstract class for AI providers
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional


class AIProvider(ABC):
    """
    Abstract base class for AI providers.
    All providers must implement these methods.
    """
    
    def __init__(self, api_key: str, model_name: str, **kwargs):
        """
        Initialize the AI provider.
        
        Args:
            api_key: API key for the provider
            model_name: Specific model to use
            **kwargs: Additional configuration (temperature, max_tokens, etc.)
        """
        self.api_key = api_key
        self.model_name = model_name
        t = kwargs.get("temperature")
        self.temperature = t if t is not None else 0.7
        m = kwargs.get("max_tokens")
        self.max_tokens = m if m is not None else 2000
        self.system_prompt_override = kwargs.get("system_prompt_override")
    
    @abstractmethod
    async def generate_message(
        self, 
        prompt: str, 
        context: Dict[str, Any]
    ) -> str:
        """
        Generate a customer service message.
        
        Args:
            prompt: The main prompt/instructions
            context: Additional context (thread history, instructions, etc.)
            
        Returns:
            Generated message text
        """
        pass
    
    @abstractmethod
    async def detect_language(self, text: str) -> str:
        """
        Detect the language of a text.
        
        Args:
            text: Text to analyze
            
        Returns:
            ISO 639-1 language code (e.g., "en", "es", "fr")
        """
        pass
    
    @abstractmethod
    async def translate(
        self, 
        text: str, 
        source_lang: str,
        target_lang: str
    ) -> Dict[str, str]:
        """
        Translate text from source to target language.
        
        Args:
            text: Text to translate
            source_lang: Source language code
            target_lang: Target language code
            
        Returns:
            Dict with "translated" and "back_translated" keys
        """
        pass
    
    @property
    def provider_name(self) -> str:
        """Get the provider name"""
        return self.__class__.__name__.replace("Provider", "").lower()
