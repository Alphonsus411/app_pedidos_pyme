"""Confirmación real y concurrencia entre conexiones SQLite independientes."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from threading import Barrier
from unittest.mock import Mock

import pytest

from universal_business.application.events.reservation_codec import ReservationEventJsonCodec
from universal_business.application.execution import execute_use_case
from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.reservations.commands import ConfirmReservation
from universal_business.application.reservations.handlers import ConfirmReservationHandler
from universal_business.domain.availability.entities import AvailabilityBlock, AvailabilityRule
from universal_business.domain.availability.value_objects import BlockReason
from universal_business.domain.business.entities import Location
from universal_business.domain.business.value_objects import Address, LocationStatus, OperatingHours
from universal_business.domain.customers.entities import Customer
from universal_business.domain.reservations.allocation import ReservationUnavailableError
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.resources.entities import Resource
from universal_business.domain.shared.value_objects.ids import (
    AvailabilityBlockId,
    AvailabilityRuleId,
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    ResourceTypeId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import DateRange, TimeRange
from universal_business.infrastructure.sqlite_availability import (
    SqliteAvailabilityRepository,
    create_sqlite_availability_schema,
)
from universal_business.infrastructure.sqlite_customers import (
    SqliteCustomerRepository,
    create_sqlite_customers_schema,
)
from universal_business.infrastructure.sqlite_idempotency import (
    SqliteReservationIdempotencyStore,
    create_sqlite_idempotency_schema,
)
from universal_business.infrastructure.sqlite_locations import (
    SqliteLocationRepository,
    create_sqlite_locations_schema,
)
from universal_business.infrastructure.sqlite_outbox import (
    SqliteOutboxWriter,
    create_sqlite_outbox_schema,
)
from universal_business.infrastructure.sqlite_reservation_allocation import (
    SqliteReservationAllocation,
)
from universal_business.infrastructure.sqlite_reservations import (
    SqliteReservationRepository,
    create_sqlite_reservations_schema,
)
from universal_business.infrastructure.sqlite_resources import (
    SqliteResourceRepository,
    create_sqlite_resources_schema,
)
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.fixture
def case(tmp_path):
    path = tmp_path / "allocation.db"
    tid, bid, lid, rid, cid = (
        TenantId.generate(),
        BusinessId.generate(),
        LocationId.generate(),
        ResourceId.generate(),
        CustomerId.generate(),
    )
    start = datetime(2026, 10, 29, 10, tzinfo=UTC)
    interval = ReservationInterval(start, start + timedelta(hours=1))
    rule = AvailabilityRule(
        id=AvailabilityRuleId.generate(),
        tenant_id=tid,
        location_id=lid,
        effective_range=DateRange.single(start.date()),
        time_ranges=[TimeRange(start, start + timedelta(hours=3))],
    )
    reservation = Reservation(
        id=ReservationId.generate(),
        tenant_id=tid,
        business_id=bid,
        location_id=lid,
        resource_id=rid,
        customer_id=cid,
        time_range=TimeRange(interval.start, interval.end),
        party_size=2,
    )
    with sqlite3.connect(path) as connection:
        for setup in (
            create_sqlite_availability_schema,
            create_sqlite_locations_schema,
            create_sqlite_resources_schema,
            create_sqlite_customers_schema,
            create_sqlite_reservations_schema,
            create_sqlite_outbox_schema,
            create_sqlite_idempotency_schema,
        ):
            setup(connection)
        with SqliteUnitOfWork(connection) as uow:
            SqliteLocationRepository(connection).save(
                Location(
                    id=lid,
                    tenant_id=tid,
                    business_id=bid,
                    name="Local",
                    address=Address(country_code="ES"),
                    timezone="UTC",
                    operating_hours=OperatingHours(),
                    status=LocationStatus.OPEN,
                )
            )
            SqliteResourceRepository(connection).save(
                Resource(
                    id=rid,
                    tenant_id=tid,
                    business_id=bid,
                    location_id=lid,
                    resource_type_id=ResourceTypeId.generate(),
                    name="Sala",
                    capacity=2,
                )
            )
            SqliteCustomerRepository(connection).save(
                Customer(id=cid, tenant_id=tid, business_id=bid, given_name="A")
            )
            SqliteReservationRepository(connection).save(reservation)
            SqliteAvailabilityRepository(connection).save_rule(rule)
            uow.commit()
    return path, reservation, rule


def confirm(path, reservation):
    with sqlite3.connect(path, timeout=10) as connection:
        uow = SqliteUnitOfWork(connection)
        handler = ConfirmReservationHandler(
            reservations=SqliteReservationRepository(connection),
            customers=SqliteCustomerRepository(connection),
            allocation=SqliteReservationAllocation(uow),
            idempotency=SqliteReservationIdempotencyStore(connection),
        )
        command = ConfirmReservation(
            tenant_id=reservation.tenant_id,
            business_id=reservation.business_id,
            location_id=reservation.location_id,
            reservation_id=reservation.id,
            idempotency_key=IdempotencyKey(value=f"confirm-{reservation.id}"),
        )
        return execute_use_case(
            handler=handler,
            input=command,
            unit_of_work=uow,
            event_dispatcher=Mock(),
            event_publisher=Mock(),
            outbox_writer=SqliteOutboxWriter(
                connection=connection, encoder=ReservationEventJsonCodec()
            ),
        )


def test_confirmation_and_replay_persist_once(case):
    path, reservation, _ = case
    first = confirm(path, reservation)
    assert confirm(path, reservation) == first
    with sqlite3.connect(path) as connection:
        actual = SqliteReservationRepository(connection).get(
            tenant_id=reservation.tenant_id, reservation_id=reservation.id
        )
        assert actual.status == ReservationStatus.CONFIRMED
        assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (1,)
        assert connection.execute("SELECT state FROM idempotency").fetchall() == [("done",)]


def test_block_prevents_confirmation_without_side_effects(case):
    path, reservation, rule = case
    block = AvailabilityBlock(
        id=AvailabilityBlockId.generate(),
        tenant_id=rule.tenant_id,
        location_id=rule.location_id,
        blocked_range=rule.effective_range,
        reason=BlockReason.HOLIDAY,
    )
    with sqlite3.connect(path) as connection:
        with SqliteUnitOfWork(connection) as uow:
            SqliteAvailabilityRepository(connection).save_block(block)
            uow.commit()
    with pytest.raises(ReservationUnavailableError, match="blocked"):
        confirm(path, reservation)
    with sqlite3.connect(path) as connection:
        assert (
            SqliteReservationRepository(connection)
            .get(tenant_id=reservation.tenant_id, reservation_id=reservation.id)
            .status
            == ReservationStatus.DRAFT
        )
        assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM idempotency").fetchone() == (0,)


def test_concurrent_overlapping_confirmations_only_one_wins(case):
    path, first, _ = case
    second = replace(first, id=ReservationId.generate())
    with sqlite3.connect(path) as connection:
        with SqliteUnitOfWork(connection) as uow:
            SqliteReservationRepository(connection).save(second)
            uow.commit()
    barrier = Barrier(2)

    def run(reservation):
        barrier.wait(timeout=5)
        try:
            confirm(path, reservation)
            return "confirmed"
        except ReservationUnavailableError:
            return "unavailable"

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(run, [first, second]))
    assert sorted(outcomes) == ["confirmed", "unavailable"]
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM reservations WHERE status='confirmed'"
        ).fetchone() == (1,)
        assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (1,)


@pytest.mark.parametrize(
    "change,reason",
    [
        ("DELETE FROM availability_rules", "outside_windows"),
        ("UPDATE resources SET capacity=1", "capacity_exceeded"),
        ("UPDATE resources SET status='inactive'", "inactive_resource"),
    ],
)
def test_unavailable_conditions_do_not_confirm(case, change, reason):
    path, reservation, _ = case
    with sqlite3.connect(path) as connection:
        connection.execute(change)
    with pytest.raises(ReservationUnavailableError, match=reason):
        confirm(path, reservation)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT status FROM reservations").fetchone() == ("draft",)
        assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (0,)


def test_adjacent_reservations_can_both_confirm(case):
    path, first, _ = case
    end = first.time_range.end
    second = replace(
        first, id=ReservationId.generate(), time_range=TimeRange(end, end + timedelta(hours=1))
    )
    with sqlite3.connect(path) as connection:
        with SqliteUnitOfWork(connection) as uow:
            SqliteReservationRepository(connection).save(second)
            uow.commit()
    confirm(path, first)
    confirm(path, second)
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT count(*) FROM reservations WHERE status='confirmed'"
        ).fetchone() == (2,)


def test_allocation_requires_uow_and_matching_snapshot(case):
    path, reservation, _ = case
    with sqlite3.connect(path) as connection:
        uow = SqliteUnitOfWork(connection)
        allocator = SqliteReservationAllocation(uow)
        args = dict(
            tenant_id=reservation.tenant_id,
            business_id=reservation.business_id,
            location_id=reservation.location_id,
            resource_id=reservation.resource_id,
            reservation_id=reservation.id,
            interval=ReservationInterval(reservation.time_range.start, reservation.time_range.end),
            party_size=3,
        )
        with pytest.raises(RuntimeError, match="activa"):
            allocator.protect_and_check(**args)
        with uow:
            with pytest.raises(ReservationUnavailableError):
                allocator.protect_and_check(**args)


def test_outbox_failure_rolls_back_confirmation(case):
    path, reservation, _ = case
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TRIGGER reject_outbox BEFORE INSERT ON transactional_outbox BEGIN SELECT RAISE(ABORT, 'outbox failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="outbox failure"):
        confirm(path, reservation)
    with sqlite3.connect(path) as connection:
        assert connection.execute("SELECT status FROM reservations").fetchone() == ("draft",)
        assert connection.execute("SELECT count(*) FROM idempotency").fetchone() == (0,)
        assert connection.execute("SELECT count(*) FROM transactional_outbox").fetchone() == (0,)
