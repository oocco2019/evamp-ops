"""
Customer service message models
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class MessageThread(Base):
    """
    eBay message threads (CS03).
    Groups messages by conversation with order/item context.
    """
    __tablename__ = "message_threads"
    
    thread_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    buyer_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, comment="eBay buyer username for display as thread title")
    ebay_item_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    ebay_order_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    sku: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    tracking_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_flagged: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Relationship to messages
    messages: Mapped[List["Message"]] = relationship(
        "Message",
        back_populates="thread",
        cascade="all, delete-orphan",
        order_by="Message.created_at"
    )
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        return f"<MessageThread {self.thread_id}>"


class Message(Base):
    """
    Individual messages within threads (CS01, CS02).
    Stores messages from eBay with metadata and status.
    """
    __tablename__ = "messages"
    
    message_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    thread_id: Mapped[str] = mapped_column(
        ForeignKey("message_threads.thread_id"), 
        nullable=False
    )
    
    # Message content
    sender_type: Mapped[str] = mapped_column(
        String(20), 
        nullable=False,
        comment="buyer, seller, system"
    )
    sender_username: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    
    # Status flags (CS02)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Language detection (CS07)
    detected_language: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    translated_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Metadata
    ebay_created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    # AI generation tracking (for quality comparison)
    generated_by_model: Mapped[Optional[str]] = mapped_column(
        String(100), 
        nullable=True,
        comment="e.g., claude-3-5-sonnet if AI-generated"
    )
    
    # Relationship
    thread: Mapped["MessageThread"] = relationship(
        "MessageThread", 
        back_populates="messages"
    )
    
    def __repr__(self) -> str:
        return f"<Message {self.message_id} from {self.sender_type}>"


class AIInstruction(Base):
    """
    Custom AI instructions for message drafting (CS06).
    Global and SKU-specific instructions.
    """
    __tablename__ = "ai_instructions"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(
        String(20), 
        nullable=False,
        comment="global or sku"
    )
    sku_code: Mapped[Optional[str]] = mapped_column(
        String(100), 
        nullable=True,
        comment="NULL for global instructions"
    )
    item_details: Mapped[Optional[str]] = mapped_column(
        Text, 
        nullable=True,
        comment="Description of the item (for SKU-specific)"
    )
    instructions: Mapped[str] = mapped_column(
        Text, 
        nullable=False,
        comment="Instructions for AI when drafting messages"
    )
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        if self.type == "global":
            return "<AIInstruction global>"
        return f"<AIInstruction SKU={self.sku_code}>"


class SyncMetadata(Base):
    """Key-value store for sync state (e.g. last message sync time for incremental fetch)."""
    __tablename__ = "sync_metadata"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
