"""
Listing video models:
  - EbayListingSkuCache: listing ID → SKU (legacy cache)
  - ListingVideoJob / ListingVideoJobItem / ListingVideoJobLog: persistent job system
    so add-video operations survive laptop sleep / browser disconnect.
"""
from datetime import datetime
from typing import Optional, List
from sqlalchemy import (
    String, DateTime, Integer, Text, Boolean, ForeignKey, Index, text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class EbayListingSkuCache(Base):
    """
    Maps eBay listing ID (item number from URL) to SKU.
    Filled by POST /api/listing-video/sync-listing-cache. Enables O(1) lookup for "get video by item number" at scale (3k–30k listings).
    """
    __tablename__ = "ebay_listing_sku_cache"

    listing_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)


# ---------------------------------------------------------------------------
# Job system
# ---------------------------------------------------------------------------

class ListingVideoJob(Base):
    """
    One row per add-video run (SKU scan or explicit item-ID list).
    The worker runs detached from the HTTP request so laptop sleep / browser
    disconnect does NOT abort the job.
    """
    __tablename__ = "listing_video_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(40), nullable=False, unique=True, index=True)
    # "sku" or "item_ids"
    mode: Mapped[str] = mapped_column(String(20), nullable=False)
    # null for item_ids mode
    sku: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    video_id: Mapped[str] = mapped_column(String(100), nullable=False)
    marketplace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    # overall job status: pending, scanning, running, done, error
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    skipped_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)

    items: Mapped[List["ListingVideoJobItem"]] = relationship(
        "ListingVideoJobItem", back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )
    logs: Mapped[List["ListingVideoJobLog"]] = relationship(
        "ListingVideoJobLog", back_populates="job", cascade="all, delete-orphan", passive_deletes=True
    )


class ListingVideoJobItem(Base):
    """
    One row per target listing for a job.
    status: pending | skipped | done | failed
    """
    __tablename__ = "listing_video_job_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("listing_video_jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_id: Mapped[str] = mapped_column(String(32), nullable=False)
    marketplace_id: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default="pending")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)

    job: Mapped["ListingVideoJob"] = relationship("ListingVideoJob", back_populates="items")

    __table_args__ = (
        Index("ix_lvji_job_status", "job_id", "status"),
    )


class ListingVideoJobLog(Base):
    """
    Append-only log lines for a job.  Fetched by the UI when polling.
    """
    __tablename__ = "listing_video_job_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("listing_video_jobs.job_id", ondelete="CASCADE"), nullable=False, index=True
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)

    job: Mapped["ListingVideoJob"] = relationship("ListingVideoJob", back_populates="logs")
