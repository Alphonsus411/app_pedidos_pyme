"""Adjudicación de reservas para el prototipo SQLite."""

from universal_business.application.availability.handlers import EvaluateResourceAvailabilityHandler
from universal_business.application.availability.queries import EvaluateResourceAvailability
from universal_business.application.errors import ApplicationError
from universal_business.domain.reservations.allocation import ReservationUnavailableError
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)
from universal_business.infrastructure.sqlite_availability import SqliteAvailabilityRepository
from universal_business.infrastructure.sqlite_locations import SqliteLocationRepository
from universal_business.infrastructure.sqlite_reservations import SqliteReservationRepository
from universal_business.infrastructure.sqlite_resources import SqliteResourceRepository
from universal_business.infrastructure.sqlite_unit_of_work import SqliteUnitOfWork


class SqliteReservationAllocation:
    """Comprueba en la conexión de una UoW activa con BEGIN IMMEDIATE.

    El ensamblaje debe usar esta UoW y conexión también para guardar la reserva,
    y todas las escrituras que puedan afectar a disponibilidad deben conservar
    el bloqueo SQLite hasta commit o rollback. No comprueba autorización.
    """

    def __init__(self, uow: SqliteUnitOfWork) -> None:
        self._uow = uow

    def protect_and_check(
        self,
        *,
        tenant_id: TenantId,
        business_id: BusinessId,
        location_id: LocationId,
        resource_id: ResourceId,
        reservation_id: ReservationId,
        interval: ReservationInterval,
        party_size: int | None,
    ) -> None:
        self._uow.require_active()
        connection = self._uow.connection
        reservations = SqliteReservationRepository(connection)
        current = reservations.get(tenant_id=tenant_id, reservation_id=reservation_id)
        if current is None or (
            current.tenant_id,
            current.business_id,
            current.location_id,
            current.resource_id,
            current.id,
            current.status,
            ReservationInterval(current.time_range.start, current.time_range.end),
            current.party_size,
        ) != (
            tenant_id,
            business_id,
            location_id,
            resource_id,
            reservation_id,
            ReservationStatus.DRAFT,
            interval,
            party_size,
        ):
            raise ReservationUnavailableError("Reserva o recurso fuera de ámbito o modificados")
        handler = EvaluateResourceAvailabilityHandler(
            locations=SqliteLocationRepository(connection),
            resources=SqliteResourceRepository(connection),
            availability=SqliteAvailabilityRepository(connection),
            reservations=reservations,
        )
        try:
            result = handler.handle(
                EvaluateResourceAvailability(
                    tenant_id=tenant_id,
                    business_id=business_id,
                    location_id=location_id,
                    resource_id=resource_id,
                    interval=interval,
                    party_size=party_size,
                )
            )
        except ApplicationError as exc:
            raise ReservationUnavailableError("Ubicación o recurso no disponibles") from exc
        if not result.available:
            raise ReservationUnavailableError(f"Recurso no disponible: {result.reason.value}")
