"""Contrato de persistencia de reservas usando un fichero SQLite real."""

import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from universal_business.domain.reservations.allocation import ReservationUnavailableError
from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import TimeRange
from universal_business.infrastructure.sqlite_reservations import (
    SqliteReservationMutationGuard,
    SqliteReservationRepository,
    create_sqlite_reservations_schema,
)
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "reservations.db"
    with sqlite3.connect(path) as connection:
        create_sqlite_reservations_schema(connection)
    return path


@pytest.fixture
def reservation() -> Reservation:
    start = datetime(2026, 10, 29, 10, tzinfo=UTC)
    return Reservation(
        id=ReservationId.generate(),
        tenant_id=TenantId.generate(),
        business_id=BusinessId.generate(),
        location_id=LocationId.generate(),
        customer_id=CustomerId.generate(),
        resource_id=ResourceId.generate(),
        time_range=TimeRange(start, start + timedelta(hours=1)),
        party_size=3,
        notes="ventana",
    )


def test_roundtrip_and_tenant_scope(db_path: Path, reservation: Reservation) -> None:
    with sqlite3.connect(db_path) as connection:
        repo = SqliteReservationRepository(connection)
        with SqliteUnitOfWork(connection) as uow:
            repo.save(reservation)
            with sqlite3.connect(db_path) as other:
                assert (
                    SqliteReservationRepository(other).get(
                        tenant_id=reservation.tenant_id, reservation_id=reservation.id
                    )
                    is None
                )
            uow.commit()
        assert (
            repo.get(tenant_id=reservation.tenant_id, reservation_id=reservation.id) == reservation
        )
        assert repo.get(tenant_id=TenantId.generate(), reservation_id=reservation.id) is None


def test_rollback_and_scope_change_rejected(db_path: Path, reservation: Reservation) -> None:
    with sqlite3.connect(db_path) as connection:
        repo = SqliteReservationRepository(connection)
        with SqliteUnitOfWork(connection):
            repo.save(reservation)
        assert repo.get(tenant_id=reservation.tenant_id, reservation_id=reservation.id) is None
        with SqliteUnitOfWork(connection) as uow:
            repo.save(reservation)
            uow.commit()
        with pytest.raises(ValueError, match="ámbito"):
            with SqliteUnitOfWork(connection):
                repo.save(replace(reservation, business_id=BusinessId.generate()))
        assert (
            repo.get(tenant_id=reservation.tenant_id, reservation_id=reservation.id) == reservation
        )
        with pytest.raises(RuntimeError, match="transacción"):
            repo.save(reservation)


def test_full_resource_candidates_boundary_and_customer_filters(
    db_path: Path, reservation: Reservation
) -> None:
    before = replace(
        reservation,
        id=ReservationId.generate(),
        status=ReservationStatus.CANCELLED,
        time_range=TimeRange(
            reservation.time_range.start - timedelta(hours=1), reservation.time_range.start
        ),
    )
    other_tenant = replace(reservation, id=ReservationId.generate(), tenant_id=TenantId.generate())
    with sqlite3.connect(db_path) as connection:
        repo = SqliteReservationRepository(connection)
        with SqliteUnitOfWork(connection) as uow:
            for item in (reservation, before, other_tenant):
                repo.save(item)
            uow.commit()
        candidates = repo.list_for_resource_in_range(
            tenant_id=reservation.tenant_id,
            location_id=reservation.location_id,
            resource_id=reservation.resource_id,
            time_range=reservation.time_range,
        )
        assert {item.id for item in candidates} == {reservation.id, before.id}
        assert repo.list_for_customer(
            tenant_id=reservation.tenant_id,
            customer_id=reservation.customer_id,
            status=ReservationStatus.CANCELLED,
        ) == [before]


def test_update_and_distinct_tenants_with_same_id(db_path: Path, reservation: Reservation) -> None:
    other = replace(reservation, tenant_id=TenantId.generate(), business_id=BusinessId.generate())
    with sqlite3.connect(db_path) as connection:
        repo = SqliteReservationRepository(connection)
        with SqliteUnitOfWork(connection) as uow:
            repo.save(reservation)
            repo.save(other)
            uow.commit()
        changed = replace(reservation, status=ReservationStatus.CONFIRMED, notes="confirmada")
        with SqliteUnitOfWork(connection) as uow:
            repo.save(changed)
            uow.commit()
        assert repo.get(tenant_id=reservation.tenant_id, reservation_id=reservation.id) == changed
        assert repo.get(tenant_id=other.tenant_id, reservation_id=other.id) == other


def test_candidates_compare_instants_across_offsets(
    db_path: Path, reservation: Reservation
) -> None:
    start = reservation.time_range.start.astimezone(timezone(timedelta(hours=2)))
    query = TimeRange(start, start + timedelta(minutes=30))
    with sqlite3.connect(db_path) as connection:
        repo = SqliteReservationRepository(connection)
        with SqliteUnitOfWork(connection) as uow:
            repo.save(reservation)
            uow.commit()
        assert repo.list_for_resource_in_range(
            tenant_id=reservation.tenant_id,
            location_id=reservation.location_id,
            resource_id=reservation.resource_id,
            time_range=query,
        ) == [reservation]


def test_list_by_location_filters_before_limit_and_scope(
    db_path: Path, reservation: Reservation
) -> None:
    other_business = replace(
        reservation, id=ReservationId.generate(), business_id=BusinessId.generate()
    )
    second = replace(reservation, id=ReservationId.generate(), status=ReservationStatus.CONFIRMED)
    with sqlite3.connect(db_path) as connection:
        repo = SqliteReservationRepository(connection)
        with SqliteUnitOfWork(connection) as uow:
            for item in (reservation, other_business, second):
                repo.save(item)
            uow.commit()
        query = dict(
            tenant_id=reservation.tenant_id,
            business_id=reservation.business_id,
            location_id=reservation.location_id,
            status=ReservationStatus.CONFIRMED,
            limit=1,
        )
        assert repo.list_by_location(**query) == [second]
        assert repo.list_by_location(**(query | {"business_id": BusinessId.generate()})) == []
        for invalid in (0, 101, True):
            with pytest.raises(ValueError, match="límite"):
                repo.list_by_location(**(query | {"limit": invalid}))


def test_mutation_guard_requires_uow_scope_and_blocks_second_writer(
    db_path: Path, reservation: Reservation
) -> None:
    with sqlite3.connect(db_path) as first, sqlite3.connect(db_path, timeout=0.05) as second:
        repo = SqliteReservationRepository(first)
        with SqliteUnitOfWork(first) as setup:
            repo.save(reservation)
            setup.commit()
        uow = SqliteUnitOfWork(first)
        guard = SqliteReservationMutationGuard(uow)
        args = dict(
            tenant_id=reservation.tenant_id,
            business_id=reservation.business_id,
            location_id=reservation.location_id,
            resource_id=reservation.resource_id,
            reservation_id=reservation.id,
        )
        with pytest.raises(RuntimeError, match="UoW SQLite activa"):
            guard.protect(**args)
            with pytest.raises(ReservationUnavailableError):
                guard.protect(**(args | {"tenant_id": TenantId.generate()}))
        with uow:
            guard.protect(**args)
            with pytest.raises(ReservationUnavailableError):
                guard.protect(**(args | {"business_id": BusinessId.generate()}))
            with pytest.raises(ReservationUnavailableError):
                guard.protect(**(args | {"resource_id": ResourceId.generate()}))
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                with SqliteUnitOfWork(second):
                    pass
        with SqliteUnitOfWork(second) as other:
            SqliteReservationMutationGuard(other).protect(**args)
