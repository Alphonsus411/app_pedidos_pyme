"""Repositorio SQLite de reservas para el prototipo; no incluye adjudicación."""

import sqlite3
from datetime import UTC, datetime
from typing import Any

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
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


def create_sqlite_reservations_schema(connection: sqlite3.Connection) -> None:
    """Instala el esquema inicial; no reemplaza un sistema de migraciones."""
    connection.execute("""CREATE TABLE IF NOT EXISTS reservations (
        tenant_id TEXT NOT NULL, id TEXT NOT NULL, business_id TEXT NOT NULL,
        location_id TEXT NOT NULL, customer_id TEXT NOT NULL, resource_id TEXT NOT NULL,
        start_local TEXT NOT NULL, end_local TEXT NOT NULL,
        start_utc TEXT NOT NULL, end_utc TEXT NOT NULL,
        status TEXT NOT NULL, party_size INTEGER, notes TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        PRIMARY KEY (tenant_id, id)
    )""")
    connection.execute("""CREATE INDEX IF NOT EXISTS reservations_resource_time
        ON reservations (tenant_id, location_id, resource_id, start_utc, end_utc)""")
    connection.execute("""CREATE INDEX IF NOT EXISTS reservations_customer
        ON reservations (tenant_id, customer_id)""")


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _interval(time_range: TimeRange) -> tuple[str, str]:
    start, end = _utc(time_range.start), _utc(time_range.end)
    if start > end:
        raise ValueError("Intervalo invertido en UTC")
    return start, end


def _from_row(row: tuple[Any, ...]) -> Reservation:
    return Reservation(
        tenant_id=TenantId.from_raw(row[0]),
        id=ReservationId.from_raw(row[1]),
        business_id=BusinessId.from_raw(row[2]),
        location_id=LocationId.from_raw(row[3]),
        customer_id=CustomerId.from_raw(row[4]),
        resource_id=ResourceId.from_raw(row[5]),
        time_range=TimeRange(datetime.fromisoformat(row[6]), datetime.fromisoformat(row[7])),
        status=ReservationStatus(row[10]),
        party_size=row[11],
        notes=row[12],
        created_at=datetime.fromisoformat(row[13]),
        updated_at=datetime.fromisoformat(row[14]),
    )


class SqliteReservationRepository:
    """Lecturas aisladas por tenant y escritura dentro de transacción activa.

    Para actualizaciones concurrentes la conexión debe pertenecer a un UoW
    con BEGIN IMMEDIATE, que debe envolver también la lectura. No comprueba
    disponibilidad ni autoriza al actor. Conserva instantes y offsets, no el
    identificador IANA de la zona. El ensamblaje controla conexión y schema.
    """

    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection

    def get(self, *, tenant_id: TenantId, reservation_id: ReservationId) -> Reservation | None:
        row = self._connection.execute(
            "SELECT * FROM reservations WHERE tenant_id = ? AND id = ?",
            (str(tenant_id), str(reservation_id)),
        ).fetchone()
        return _from_row(row) if row else None

    def save(self, reservation: Reservation) -> None:
        if not self._connection.in_transaction:
            raise RuntimeError("La escritura requiere una transacción activa")
        start, end = _interval(reservation.time_range)
        params = (
            str(reservation.tenant_id),
            str(reservation.id),
            str(reservation.business_id),
            str(reservation.location_id),
            str(reservation.customer_id),
            str(reservation.resource_id),
            reservation.time_range.start.isoformat(),
            reservation.time_range.end.isoformat(),
            start,
            end,
            reservation.status.value,
            reservation.party_size,
            reservation.notes,
            reservation.created_at.isoformat(),
            reservation.updated_at.isoformat(),
        )
        result = self._connection.execute(
            """INSERT INTO reservations VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, id) DO UPDATE SET
            customer_id=excluded.customer_id, resource_id=excluded.resource_id,
            start_local=excluded.start_local, end_local=excluded.end_local,
            start_utc=excluded.start_utc, end_utc=excluded.end_utc, status=excluded.status,
            party_size=excluded.party_size, notes=excluded.notes, updated_at=excluded.updated_at
            WHERE reservations.business_id=excluded.business_id
              AND reservations.location_id=excluded.location_id
              AND reservations.created_at=excluded.created_at""",
            params,
        )
        if result.rowcount != 1:
            raise ValueError("No se puede cambiar el ámbito o la fecha de creación de la reserva")

    def list_for_resource_in_range(
        self,
        *,
        tenant_id: TenantId,
        location_id: LocationId,
        resource_id: ResourceId | None = None,
        time_range: TimeRange,
        status: ReservationStatus | None = None,
    ) -> list[Reservation]:
        start, end = _interval(time_range)
        sql = "SELECT * FROM reservations WHERE tenant_id=? AND location_id=? AND start_utc<=? AND end_utc>=?"
        params: list[object] = [str(tenant_id), str(location_id), end, start]
        if resource_id is not None:
            sql += " AND resource_id=?"
            params.append(str(resource_id))
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        return [_from_row(row) for row in self._connection.execute(sql, params).fetchall()]

    def list_for_customer(
        self,
        *,
        tenant_id: TenantId,
        customer_id: CustomerId,
        status: ReservationStatus | None = None,
    ) -> list[Reservation]:
        sql = "SELECT * FROM reservations WHERE tenant_id=? AND customer_id=?"
        params: list[object] = [str(tenant_id), str(customer_id)]
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        return [_from_row(row) for row in self._connection.execute(sql, params).fetchall()]

    def list_by_location(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        status: ReservationStatus | None,
        limit: int,
    ) -> list[Reservation]:
        """Lista acotada dentro del ámbito completo, sin prometer orden ni paginación."""
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("El límite debe estar entre 1 y 100")
        if status is not None and not isinstance(status, ReservationStatus):
            raise ValueError("Estado de reserva inválido")
        sql = "SELECT * FROM reservations WHERE tenant_id=? AND business_id=? AND location_id=?"
        params: list[object] = [str(tenant_id), str(business_id), str(location_id)]
        if status is not None:
            sql += " AND status=?"
            params.append(status.value)
        sql += " ORDER BY id LIMIT ?"
        params.append(limit)
        return [_from_row(row) for row in self._connection.execute(sql, params).fetchall()]


class SqliteReservationMutationGuard:
    """Protección SQLite asociada a una UoW BEGIN IMMEDIATE de uso único.

    Todos los cambios de recursos y disponibilidad deben usar protección
    compatible. El ensamblaje debe compartir la conexión de la UoW y no
    ejecutar BEGIN/COMMIT/ROLLBACK manualmente. No comprueba disponibilidad.
    """

    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def protect(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        resource_id: ResourceId,
        reservation_id: ReservationId,
    ) -> None:
        self._uow.require_active()
        repo = SqliteReservationRepository(self._uow.connection)
        reservation = repo.get(tenant_id=tenant_id, reservation_id=reservation_id)
        if reservation is None or (
            reservation.business_id,
            reservation.location_id,
            reservation.resource_id,
        ) != (business_id, location_id, resource_id):
            raise ReservationUnavailableError("Reserva o recurso fuera de ámbito")
