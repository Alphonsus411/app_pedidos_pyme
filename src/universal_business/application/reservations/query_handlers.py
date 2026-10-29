"""Lectura informativa de una reserva."""

from dataclasses import dataclass
from datetime import datetime

from universal_business.application.errors import ApplicationError
from universal_business.application.reservations.queries import GetReservation
from universal_business.domain.reservations.ports import IReservationRepository
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


@dataclass(frozen=True, kw_only=True)
class ReservationView:
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    reservation_id: ReservationId
    customer_id: CustomerId
    resource_id: ResourceId
    time_range: TimeRange
    status: ReservationStatus
    party_size: int | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


class GetReservationHandler:
    """Consulta informativa; la frontera debe autorizar al actor.

    El repositorio debe aislar tenant y proveer lectura coherente; la consulta
    no promete snapshot transaccional ni adjudica disponibilidad.
    """

    def __init__(self, *, reservations: IReservationRepository) -> None:
        self._reservations = reservations

    def handle(self, query: GetReservation, /) -> ReservationView | None:
        if not all(
            (
                isinstance(query.tenant_id, TenantId),
                isinstance(query.business_id, BusinessId),
                isinstance(query.location_id, LocationId),
                isinstance(query.reservation_id, ReservationId),
            )
        ):
            raise ApplicationError("Ámbito o identificador de reserva inválido")
        reservation = self._reservations.get(
            tenant_id=query.tenant_id, reservation_id=query.reservation_id
        )
        if reservation is None or (
            reservation.tenant_id,
            reservation.business_id,
            reservation.location_id,
            reservation.id,
        ) != (query.tenant_id, query.business_id, query.location_id, query.reservation_id):
            return None
        if not isinstance(reservation.time_range, TimeRange) or not isinstance(
            reservation.status, ReservationStatus
        ):
            raise ApplicationError("Reserva inválida devuelta por repositorio")
        return ReservationView(
            tenant_id=reservation.tenant_id,
            business_id=reservation.business_id,
            location_id=reservation.location_id,
            reservation_id=reservation.id,
            customer_id=reservation.customer_id,
            resource_id=reservation.resource_id,
            time_range=reservation.time_range,
            status=reservation.status,
            party_size=reservation.party_size,
            notes=reservation.notes,
            created_at=reservation.created_at,
            updated_at=reservation.updated_at,
        )
