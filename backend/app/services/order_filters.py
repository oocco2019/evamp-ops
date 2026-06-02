"""Shared SQL filters for marketplace order queries."""

from sqlalchemy import or_

from app.models.stock import Order


def order_not_canceled_filter():
    """Include active orders; Shopify and legacy imports store non-cancelled as NULL."""
    return or_(Order.cancel_status.is_(None), Order.cancel_status != "CANCELED")
