"""
Application configuration and settings
"""
from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""
    
    # Application
    DEBUG: bool = False
    APP_NAME: str = "EvampOps"
    VERSION: str = "0.1.0"
    
    # Database
    DATABASE_URL: str
    
    # Security
    ENCRYPTION_KEY: str
    SECRET_KEY: str = "your-secret-key-change-in-production"
    
    # CORS
    CORS_ORIGINS: str = "http://localhost:5173"
    
    # eBay API
    EBAY_APP_ID: str = ""
    EBAY_CERT_ID: str = ""
    EBAY_DEV_ID: str = ""
    EBAY_WEBHOOK_SECRET: str = ""
    EBAY_API_URL: str = "https://api.ebay.com"
    EBAY_AUTH_URL: str = "https://auth.ebay.com/oauth2"
    
    # AI Providers (can be set via UI)
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    
    # Rate Limiting
    MAX_AI_REQUESTS_PER_HOUR: int = 100
    MAX_AI_TOKENS_PER_REQUEST: int = 4000
    
    # Background Tasks
    MESSAGE_SYNC_INTERVAL_MINUTES: int = 60
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )
    
    @property
    def cors_origins_list(self) -> List[str]:
        """Parse CORS origins from comma-separated string"""
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",")]


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Global settings instance
settings = get_settings()
