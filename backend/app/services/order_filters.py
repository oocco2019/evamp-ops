"""Shared SQL predicates for imported marketplace orders."""

from sqlalchemy import or_

from app.models.stock import Order


def order_not_canceled_condition():
    """Include open orders where cancel_status is NULL, as Shopify stores open orders that way."""
    return or_(Order.cancel_status.is_(None), Order.cancel_status != "CANCELED")
