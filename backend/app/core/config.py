"""
Application configuration and settings
"""
from functools import lru_cache
from typing import List
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _strip_quotes_and_whitespace(v: str) -> str:
    if not isinstance(v, str):
        return v
    v = v.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ('"', "'"):
        v = v[1:-1].strip()
    return v


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
    
    # CORS & Frontend (for OAuth redirects)
    CORS_ORIGINS: str = "http://localhost:5173"
    FRONTEND_URL: str = "http://localhost:5173"
    
    # eBay API (from .env)
    EBAY_APP_ID: str = ""
    EBAY_CERT_ID: str = ""
    EBAY_DEV_ID: str = ""
    EBAY_WEBHOOK_SECRET: str = ""
    EBAY_REDIRECT_URI: str = ""  # RuName from eBay Developer Portal (Production RuName when using auth.ebay.com)
    # Tunnel URL (e.g. https://xxx.localhost.run) so the app can show the full callback URL to paste in eBay
    CALLBACK_BASE_URL: str = ""
    EBAY_API_URL: str = "https://api.ebay.com"
    # Marketplace for Finances API (required header). E.g. EBAY_GB, EBAY_US.
    EBAY_MARKETPLACE_ID: str = "EBAY_GB"
    EBAY_AUTH_URL: str = "https://auth.ebay.com/oauth2"
    EBAY_IDENTITY_URL: str = "https://api.ebay.com/identity/v1/oauth2"
    # Optional: seller eBay username for classifying message sender_type (buyer vs seller)
    EBAY_SELLER_USERNAME: str = ""

    # Sales Analytics profit: convert USD/EUR to GBP (landed cost, postage; order amounts)
    USD_TO_GBP_RATE: float = 0.79
    EUR_TO_GBP_RATE: float = 0.86
    # Profit after tax: displayed profit = gross profit * (1 - PROFIT_TAX_RATE). E.g. 0.30 = 30% tax on profit (take-home 70%).
    PROFIT_TAX_RATE: float = 0.30

    # AI Providers (can be set via UI)
    ANTHROPIC_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    
    # Rate Limiting
    MAX_AI_REQUESTS_PER_HOUR: int = 100
    MAX_AI_TOKENS_PER_REQUEST: int = 4000
    
    # Background Tasks
    MESSAGE_SYNC_INTERVAL_MINUTES: int = 60

    # Message sending (Phase 4-6): set True only when ready to test replying to real customers
    ENABLE_MESSAGE_SENDING: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True
    )

    @field_validator("EBAY_REDIRECT_URI", mode="before")
    @classmethod
    def normalize_ebay_redirect_uri(cls, v: str) -> str:
        """Strip surrounding quotes and whitespace so .env values match eBay exactly."""
        return _strip_quotes_and_whitespace(v) if v else ""

    @field_validator("CALLBACK_BASE_URL", mode="before")
    @classmethod
    def normalize_callback_base_url(cls, v: str) -> str:
        """Strip quotes/whitespace and trailing slash for building callback URL."""
        u = _strip_quotes_and_whitespace(v) if v else ""
        return u.rstrip("/") if u else ""
    
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
