import asyncio

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.api.inventory_status import _find_inbound_order_for_override
from app.core.database import Base
from app.models.settings import OCInboundOrder


class AsyncSessionShim:
    def __init__(self, session: Session):
        self.session = session

    async def execute(self, stmt):
        return self.session.execute(stmt)


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_inbound_override_lookup_requires_both_identifiers_when_both_are_sent(session):
    wrong_shared_seller = OCInboundOrder(
        connection_id=1,
        dedup_key="OC-B::PO-1",
        seller_inbound_number="PO-1",
        oc_inbound_number="OC-B",
    )
    target = OCInboundOrder(
        connection_id=1,
        dedup_key="OC-A::PO-1",
        seller_inbound_number="PO-1",
        oc_inbound_number="OC-A",
    )
    session.add_all([wrong_shared_seller, target])
    session.commit()

    row = asyncio.run(
        _find_inbound_order_for_override(
            AsyncSessionShim(session),
            1,
            oc_inbound_number="OC-A",
            seller_inbound_number="PO-1",
        )
    )

    assert row.id == target.id


def test_inbound_override_lookup_rejects_ambiguous_seller_only_match(session):
    session.add_all(
        [
            OCInboundOrder(
                connection_id=1,
                dedup_key="OC-A::PO-1",
                seller_inbound_number="PO-1",
                oc_inbound_number="OC-A",
            ),
            OCInboundOrder(
                connection_id=1,
                dedup_key="OC-B::PO-1",
                seller_inbound_number="PO-1",
                oc_inbound_number="OC-B",
            ),
        ]
    )
    session.commit()

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            _find_inbound_order_for_override(
                AsyncSessionShim(session),
                1,
                oc_inbound_number=None,
                seller_inbound_number="PO-1",
            )
        )

    assert exc.value.status_code == 409
