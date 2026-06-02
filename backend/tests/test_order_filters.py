from datetime import date, datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from app.core.database import Base
from app.models.stock import Order
from app.services.order_filters import order_not_canceled_filter


def _order(external_id: str, cancel_status: str | None) -> Order:
    return Order(
        sales_channel="shopify",
        ebay_order_id=external_id,
        date=date(2026, 1, 1),
        country="GB",
        last_modified=datetime(2026, 1, 1, 12, 0, 0),
        cancel_status=cancel_status,
    )


def test_order_not_canceled_filter_includes_null_and_excludes_canceled():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        session.add_all(
            [
                _order("shopify-active-null", None),
                _order("ebay-active", "NONE_REQUESTED"),
                _order("shopify-canceled", "CANCELED"),
            ]
        )
        session.commit()

        rows = session.execute(
            select(Order.ebay_order_id).where(order_not_canceled_filter()).order_by(Order.ebay_order_id)
        ).scalars().all()

    assert rows == ["ebay-active", "shopify-active-null"]
