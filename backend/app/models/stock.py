"""
Stock management models
"""
from datetime import datetime, date
from typing import Optional, List
from decimal import Decimal
from sqlalchemy import (
    String, Integer, DateTime, Date, Numeric, 
    ForeignKey, Text, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.core.database import Base


class Order(Base):
    """
    eBay orders imported via API (SM02).
    Used for sales analytics (SM01).
    """
    __tablename__ = "orders"
    
    order_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ebay_order_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    country: Mapped[str] = mapped_column(String(2), nullable=False)
    last_modified: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    
    # Relationship to line items
    line_items: Mapped[List["LineItem"]] = relationship(
        "LineItem",
        back_populates="order",
        cascade="all, delete-orphan"
    )
    
    __table_args__ = (
        UniqueConstraint('ebay_order_id', name='uq_ebay_order_id'),
    )
    
    def __repr__(self) -> str:
        return f"<Order {self.ebay_order_id} ({self.country})>"


class LineItem(Base):
    """
    Individual items within an order.
    Deduplication by OrderID + LineItemID (SM02).
    """
    __tablename__ = "line_items"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.order_id"), nullable=False)
    ebay_line_item_id: Mapped[str] = mapped_column(String(100), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    
    # Relationship
    order: Mapped["Order"] = relationship("Order", back_populates="line_items")
    
    __table_args__ = (
        UniqueConstraint('order_id', 'ebay_line_item_id', name='uq_order_line_item'),
    )
    
    def __repr__(self) -> str:
        return f"<LineItem {self.sku} qty={self.quantity}>"


class SKU(Base):
    """
    Product catalog with costs and profit calculations (SM03).
    Used in stock planning (SM04) and order generation (SM06).
    """
    __tablename__ = "skus"
    
    sku_code: Mapped[str] = mapped_column(String(100), primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Optional cost fields
    landed_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), 
        nullable=True,
        comment="Cost to receive item"
    )
    postage_price: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), 
        nullable=True
    )
    profit_per_unit: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2), 
        nullable=True
    )
    currency: Mapped[str] = mapped_column(
        String(3), 
        nullable=False, 
        default="USD",
        comment="ISO 4217 currency code"
    )
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        return f"<SKU {self.sku_code}: {self.title}>"


class PurchaseOrder(Base):
    """
    Supplier purchase orders (SM07).
    Tracks orders placed with suppliers.
    """
    __tablename__ = "purchase_orders"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(
        String(20), 
        nullable=False, 
        default="In Progress",
        comment="In Progress, Done"
    )
    order_date: Mapped[date] = mapped_column(Date, nullable=False)
    order_value: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    lead_time_days: Mapped[int] = mapped_column(
        Integer, 
        nullable=False, 
        default=90,
        comment="Expected days until delivery"
    )
    actual_delivery_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    
    # Calculated fields (can be properties)
    @property
    def deposit(self) -> Decimal:
        """20% deposit"""
        return self.order_value * Decimal("0.20")
    
    @property
    def final_payment(self) -> Decimal:
        """80% final payment"""
        return self.order_value * Decimal("0.80")
    
    # Relationship to line items
    line_items: Mapped[List["POLineItem"]] = relationship(
        "POLineItem",
        back_populates="purchase_order",
        cascade="all, delete-orphan"
    )
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow
    )
    
    def __repr__(self) -> str:
        return f"<PurchaseOrder #{self.id} {self.status} ${self.order_value}>"


class POLineItem(Base):
    """
    Line items for purchase orders.
    Tracks what was ordered in each PO.
    """
    __tablename__ = "po_line_items"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    po_id: Mapped[int] = mapped_column(
        ForeignKey("purchase_orders.id"), 
        nullable=False
    )
    sku_code: Mapped[str] = mapped_column(
        ForeignKey("skus.sku_code"), 
        nullable=False
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Relationships
    purchase_order: Mapped["PurchaseOrder"] = relationship(
        "PurchaseOrder", 
        back_populates="line_items"
    )
    
    def __repr__(self) -> str:
        return f"<POLineItem PO#{self.po_id} {self.sku_code} qty={self.quantity}>"
