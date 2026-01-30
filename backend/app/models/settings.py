"""
Settings and configuration models
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Text, Integer
from sqlalchemy.orm import Mapped, mapped_column
from app.core.database import Base


class APICredential(Base):
    """
    Stores encrypted API credentials for various services.
    GN01 requirement: secure API key storage
    """
    __tablename__ = "api_credentials"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_name: Mapped[str] = mapped_column(String(50), nullable=False)
    key_name: Mapped[str] = mapped_column(String(100), nullable=False)
    encrypted_value: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        return f"<APICredential {self.service_name}:{self.key_name}>"


class AIModelSetting(Base):
    """
    Stores AI model configuration and selection.
    Allows users to choose which AI provider and model to use.
    """
    __tablename__ = "ai_model_settings"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(
        String(50), 
        nullable=False,
        comment="anthropic, openai, or litellm"
    )
    model_name: Mapped[str] = mapped_column(
        String(100), 
        nullable=False,
        comment="e.g., claude-3-5-sonnet-20241022, gpt-4-turbo-preview"
    )
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Optional parameters
    temperature: Mapped[Optional[float]] = mapped_column(nullable=True, default=0.7)
    max_tokens: Mapped[Optional[int]] = mapped_column(nullable=True, default=2000)
    system_prompt_override: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        return f"<AIModelSetting {self.provider}:{self.model_name} default={self.is_default}>"


class Warehouse(Base):
    """
    Warehouse addresses for SM05.
    Used in supplier order messages (SM06).
    """
    __tablename__ = "warehouses"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shortname: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    address: Mapped[str] = mapped_column(Text, nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        return f"<Warehouse {self.shortname} ({self.country_code})>"
