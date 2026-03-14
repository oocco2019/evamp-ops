"""
Listing video: cache of eBay listing ID → SKU for fast lookup.
Populated by sync job (getInventoryItems + getOffers). Avoids scanning all inventory on every "get video by item number" request.
"""
from datetime import datetime
from sqlalchemy import String, DateTime
from sqlalchemy.orm import Mapped, mapped_column
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
