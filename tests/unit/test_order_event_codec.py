"""Codec de pedidos y recorrido con outbox SQLite."""

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from universal_business.application.events.business_event_codec import BusinessEventJsonCodec
from universal_business.application.events.order_codec import OrderEventJsonCodec
from universal_business.application.events.outbox_delivery import OutboxDeliveryWorker
from universal_business.domain.orders.events import (
    OrderCreated,
    OrderLineAdded,
    OrderLineRemoved,
    OrderStatusChanged,
)
from universal_business.domain.orders.value_objects import OrderStatus
from universal_business.domain.reservations.events import ReservationCreated
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    OfferingId,
    OrderId,
    ReservationId,
    ResourceId,
    TenantId,
)
from universal_business.infrastructure.sqlite_outbox import (
    SqliteOutboxDeliveryStore,
    SqliteOutboxWriter,
    create_sqlite_delivery_schema,
    create_sqlite_outbox_schema,
)


def fields() -> dict:
    return dict(
        aggregate_id=OrderId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        metadata={"origin": ["web", {"count": 2}]},
    )


@pytest.mark.parametrize(
    "event_type", [OrderCreated, OrderLineAdded, OrderLineRemoved, OrderStatusChanged]
)
def test_event_roundtrip(event_type: type) -> None:
    extra = {}
    if event_type in (OrderLineAdded, OrderLineRemoved):
        extra = {"line_id": uuid4(), "offering_id": OfferingId.generate()}
    if event_type is OrderStatusChanged:
        extra = {"previous_status": OrderStatus.DRAFT, "new_status": OrderStatus.CONFIRMED}
    event = event_type(**fields(), **extra)
    codec = OrderEventJsonCodec()
    assert codec.decode(codec.encode(event)) == event


@pytest.mark.parametrize("fold", [0, 1])
def test_ambiguous_local_hour(fold: int) -> None:
    instant = datetime(2026, 10, 25, 2, 30, tzinfo=ZoneInfo("Europe/Madrid"), fold=fold)
    event = OrderCreated(**fields(), occurred_at=instant)
    codec = OrderEventJsonCodec()
    assert codec.decode(codec.encode(event)).occurred_at.astimezone(UTC) == instant.astimezone(UTC)


def test_reject_corrupt_or_unsupported_fields() -> None:
    codec = OrderEventJsonCodec()
    data = json.loads(codec.encode(OrderCreated(**fields())))
    for change in ({"version": 2}, {"type": "unknown"}, {"extra": 1}):
        with pytest.raises(ValueError):
            codec.decode(json.dumps(data | change).encode())
    with pytest.raises(ValueError):
        codec.decode(b'{"version":1,"version":1}')
    with pytest.raises(ValueError, match="metadata"):
        codec.encode(OrderCreated(**(fields() | {"metadata": {"price": 1.5}})))


def test_sqlite_delivery_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "orders.db"
    event = OrderLineAdded(**fields(), line_id=uuid4(), offering_id=OfferingId.generate())
    codec = OrderEventJsonCodec()
    with sqlite3.connect(path) as connection:
        create_sqlite_outbox_schema(connection)
        create_sqlite_delivery_schema(connection)
        connection.execute("BEGIN")
        SqliteOutboxWriter(connection=connection, encoder=codec).write_many([event])
    publisher = Mock()
    store = SqliteOutboxDeliveryStore(
        connect=lambda: sqlite3.connect(path), decoder=codec, lease_seconds=30
    )
    worker = OutboxDeliveryWorker(store=store, publisher=publisher)
    assert worker.process_one()
    assert not worker.process_one()
    publisher.publish.assert_called_once_with(event)


def test_mixed_order_and_reservation_queue(tmp_path: Path) -> None:
    path = tmp_path / "mixed.db"
    order = OrderCreated(**fields())
    reservation = ReservationCreated(
        aggregate_id=ReservationId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        resource_id=ResourceId.generate(),
    )
    codec = BusinessEventJsonCodec()
    with sqlite3.connect(path) as connection:
        create_sqlite_outbox_schema(connection)
        create_sqlite_delivery_schema(connection)
        connection.execute("BEGIN")
        SqliteOutboxWriter(connection=connection, encoder=codec).write_many([order, reservation])
    publisher = Mock()
    store = SqliteOutboxDeliveryStore(
        connect=lambda: sqlite3.connect(path), decoder=codec, lease_seconds=30
    )
    worker = OutboxDeliveryWorker(store=store, publisher=publisher)
    assert worker.process_one()
    assert worker.process_one()
    assert not worker.process_one()
    assert [call.args[0] for call in publisher.publish.call_args_list] == [order, reservation]
