"""Pruebas del formato explícito para eventos de reservas."""

import json
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from universal_business.application.events.outbox_delivery import OutboxDeliveryWorker
from universal_business.application.events.reservation_codec import ReservationEventJsonCodec
from universal_business.domain.reservations.events import (
    ReservationCancelled,
    ReservationConfirmed,
    ReservationCreated,
    ReservationStatusChanged,
)
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
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
        aggregate_id=ReservationId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        resource_id=ResourceId.generate(),
        metadata={"origen": ["web", {"n": 2}]},
    )


@pytest.mark.parametrize(
    "event_type", [ReservationCreated, ReservationConfirmed, ReservationCancelled]
)
def test_roundtrip_event_types(event_type: type) -> None:
    event = event_type(**fields())
    codec = ReservationEventJsonCodec()
    assert codec.decode(codec.encode(event)) == event


def test_roundtrip_status_change() -> None:
    event = ReservationStatusChanged(
        **fields(),
        previous_status=ReservationStatus.CONFIRMED,
        new_status=ReservationStatus.CHECKED_IN,
    )
    codec = ReservationEventJsonCodec()
    assert codec.decode(codec.encode(event)) == event


def test_reject_unknown_version_type_fields_and_duplicate_key() -> None:
    codec = ReservationEventJsonCodec()
    data = json.loads(codec.encode(ReservationCreated(**fields())))
    for change in ({"version": 2}, {"type": "other"}, {"unexpected": 1}):
        with pytest.raises(ValueError):
            codec.decode(json.dumps(data | change).encode())
    with pytest.raises(ValueError, match="duplicado"):
        codec.decode(b'{"version":1,"version":1}')


def test_reject_unsupported_metadata_before_write() -> None:
    event = ReservationCreated(**(fields() | {"metadata": {"value": 1.2}}))
    with pytest.raises(ValueError, match="metadata"):
        ReservationEventJsonCodec().encode(event)


def test_full_sqlite_delivery_with_real_codec(tmp_path: Path) -> None:
    path = tmp_path / "events.db"
    event = ReservationCreated(**fields())
    codec = ReservationEventJsonCodec()
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
