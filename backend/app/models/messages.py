"""
Customer service message models
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import String, Integer, DateTime, Text, Boolean, ForeignKey, JSON
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
    last_message_preview: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)

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
    Stores messages from eBay with metadata and status. Retained indefinitely in DB
    (no purge) for warranty and long-term history; eBay may not retain messages as long.
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
    media: Mapped[Optional[list]] = mapped_column(
        JSON,
        nullable=True,
        comment="Attachments: list of {mediaName, mediaType, mediaUrl}. Types: IMAGE, DOC, PDF, TXT",
    )

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


class StyleProfile(Base):
    """
    Extracted communication style from user's message history.
    AI analyzes sent messages and stores patterns here.
    """
    __tablename__ = "style_profiles"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Extracted style elements (JSON-like text fields for flexibility)
    greeting_patterns: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Common greetings used")
    closing_patterns: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Common sign-offs used")
    tone_description: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Overall tone: friendly, professional, etc.")
    empathy_patterns: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="How empathy is expressed")
    solution_approach: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="How solutions are offered")
    common_phrases: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Frequently used phrases")
    response_length: Mapped[Optional[str]] = mapped_column(String(50), nullable=True, comment="short/medium/long")
    
    # Full style summary for AI prompt
    style_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Complete style guide for AI")
    
    # Analysis metadata
    messages_analyzed: Mapped[int] = mapped_column(Integer, default=0)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, comment="User approved this profile")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Procedure(Base):
    """
    Customer service procedures extracted or defined.
    E.g., "proof_of_fault", "return_request", "shipping_delay"
    """
    __tablename__ = "procedures"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, comment="e.g. proof_of_fault")
    display_name: Mapped[str] = mapped_column(String(200), nullable=False, comment="e.g. Ask for Proof of Fault")
    
    # Trigger phrases for auto-detection or voice commands
    trigger_phrases: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="Comma-separated phrases that trigger this procedure")
    
    # The procedure steps/instructions
    steps: Mapped[str] = mapped_column(Text, nullable=False, comment="What to do/say in this situation")
    
    # Example messages (extracted from history)
    example_messages: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="JSON array of example message IDs")
    
    # Status
    is_auto_extracted: Mapped[bool] = mapped_column(Boolean, default=False, comment="True if AI extracted this")
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False, comment="User approved this procedure")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class DraftFeedback(Base):
    """
    Tracks AI drafts and user corrections for learning.
    When user edits a draft before sending, we store both versions.
    """
    __tablename__ = "draft_feedback"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    thread_id: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # The AI-generated draft
    ai_draft: Mapped[str] = mapped_column(Text, nullable=False)
    
    # What the user actually sent (NULL if they used AI draft as-is)
    final_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Was the draft edited?
    was_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    
    # Procedure used (if any)
    procedure_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    
    # Context for learning
    buyer_message_summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True, comment="What the buyer asked")
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
