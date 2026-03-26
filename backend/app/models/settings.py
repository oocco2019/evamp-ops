"""
Settings and configuration models
"""
from datetime import datetime
from typing import Optional
from sqlalchemy import String, Boolean, DateTime, Text, Integer, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
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


class EmailTemplate(Base):
    """
    Email templates for warehouse inquiries (CS11).
    Variables: {tracking_number}, {order_date}, {delivery_country}, {order_id}, {buyer_username}
    """
    __tablename__ = "email_templates"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    recipient_email: Mapped[str] = mapped_column(String(255), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        return f"<EmailTemplate {self.name}>"


class OCConnection(Base):
    """
    OrangeConnex API connection profile.
    Single active connection is used by inventory status integration.
    """

    __tablename__ = "oc_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="OC")
    region: Mapped[str] = mapped_column(String(10), nullable=False, default="UK")
    environment: Mapped[str] = mapped_column(String(10), nullable=False, default="stage")
    oauth_base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    api_base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    signature_mode: Mapped[str] = mapped_column(
        String(20), nullable=False, default="path_and_body",
        comment="path_only or path_and_body"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.utcnow,
        onupdate=datetime.utcnow
    )

    sku_mappings: Mapped[list["OCSkuMapping"]] = relationship(
        "OCSkuMapping",
        back_populates="connection",
        cascade="all, delete-orphan",
    )


class OCSkuMapping(Base):
    """
    Mapping between local sku_code and OrangeConnex SKU identifiers.
    """

    __tablename__ = "oc_sku_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("oc_connections.id"), nullable=False)
    sku_code: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    seller_skuid: Mapped[str] = mapped_column(String(100), nullable=False)
    reference_skuid: Mapped[str] = mapped_column(String(100), nullable=False)
    mfskuid: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    service_region: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    connection: Mapped["OCConnection"] = relationship("OCConnection", back_populates="sku_mappings")

    __table_args__ = (
        UniqueConstraint("connection_id", "sku_code", "mfskuid", name="uq_oc_mapping_conn_sku_mf"),
    )


class OCSkuInventory(Base):
    """
    Inventory quantities from OC StockSnapshot v2.
    """

    __tablename__ = "oc_sku_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("oc_connections.id"), nullable=False)
    mfskuid: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    service_region: Mapped[str] = mapped_column(String(20), nullable=False, default="UK")
    available: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    in_transit: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    received: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_allocated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_hold: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reserved_vas: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    suspend: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unfulfillable: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("connection_id", "mfskuid", "service_region", name="uq_oc_inventory_conn_mf_region"),
    )


class OCInboundOrder(Base):
    """
    Cached OrangeConnex inbound orders (synced from OC API; avoids repeated long fetches).
    """

    __tablename__ = "oc_inbound_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("oc_connections.id", ondelete="CASCADE"), nullable=False)
    dedup_key: Mapped[str] = mapped_column(String(320), nullable=False)
    seller_inbound_number: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    oc_inbound_number: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    status: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    warehouse_code: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    region: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    shipping_method: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    sku_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    put_away_qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inbound_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    raw_payload: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("connection_id", "dedup_key", name="uq_oc_inbound_conn_dedup"),
    )
