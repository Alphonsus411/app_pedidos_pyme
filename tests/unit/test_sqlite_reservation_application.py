"""Creación de reserva con persistencia y outbox SQLite reales."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import Mock

from tests.unit.test_application_reservation_confirm import Customers, LockedStore
from tests.unit.test_application_reservation_create import FixedRepo
from universal_business.application.events.reservation_codec import ReservationEventJsonCodec
from universal_business.application.execution import execute_use_case
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.reservations.commands import CreateReservation
from universal_business.application.reservations.creation import CreateReservationHandler
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.customers.entities import Customer
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.resources.entities import Resource
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)
from universal_business.infrastructure.sqlite_outbox import (
    SqliteOutboxWriter,
    create_sqlite_outbox_schema,
)
from universal_business.infrastructure.sqlite_reservations import (
    SqliteReservationRepository,
    create_sqlite_reservations_schema,
)
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


def test_create_reservation_and_event_commit_together(tmp_path: Path) -> None:
    path = tmp_path / "application.db"
    with sqlite3.connect(path) as setup:
        create_sqlite_reservations_schema(setup)
        create_sqlite_outbox_schema(setup)
    tid, bid, lid, rid, cid = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        ResourceId.generate(),
        CustomerId.generate(),
    )
    location = Location(
        id=lid,
        tenant_id=tid,
        business_id=bid,
        name="Local",
        address=Address(country_code="ES"),
        timezone="Europe/Madrid",
        operating_hours=OperatingHours(),
        status=LocationStatus.OPEN,
    )
    resource = Resource(
        id=rid,
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        resource_type_id=ResourceTypeId.generate(),
        name="Sala",
        capacity=2,
    )
    customer = Customer(id=cid, tenant_id=tid, business_id=bid, given_name="A")
    start = datetime(2026, 10, 29, 10, tzinfo=UTC)
    command = CreateReservation(
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        resource_id=rid,
        customer_id=cid,
        reservation_id=ReservationId.generate(),
        interval=ReservationInterval(start, start + timedelta(hours=1)),
        idempotency_key=IdempotencyKey(value="create-res-001"),
        party_size=2,
    )
    connection = sqlite3.connect(path)
    try:
        repo = SqliteReservationRepository(connection)
        handler = CreateReservationHandler(
            reservations=repo,
            customers=Customers(customer),
            locations=FixedRepo(location),
            resources=FixedRepo(resource),
            idempotency=LockedStore(),
        )
        result = execute_use_case(
            handler=handler,
            input=command,
            unit_of_work=SqliteUnitOfWork(connection),
            event_dispatcher=Mock(),
            event_publisher=Mock(),
            outbox_writer=SqliteOutboxWriter(
                connection=connection, encoder=ReservationEventJsonCodec()
            ),
        )
        assert result.reservation_id == command.reservation_id
        with sqlite3.connect(path) as reader:
            actual = SqliteReservationRepository(reader).get(
                tenant_id=tid, reservation_id=command.reservation_id
            )
            assert actual is not None and actual.status == ReservationStatus.DRAFT
            assert reader.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (1,)
    finally:
        connection.close()
