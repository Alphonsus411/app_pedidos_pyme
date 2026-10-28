"""Detección pura de solapes con reservas de un recurso y ámbito explícitos."""

from __future__ import annotations

from collections.abc import Iterable

from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.reservations.lifecycle import reservation_occupies_interval
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)


def conflicting_reservation_ids(
    *,
    tenant_id: TenantId,
    business_id: BusinessId,
    location_id: LocationId,
    resource_id: ResourceId,
    interval: ReservationInterval,
    reservations: Iterable[Reservation],
) -> tuple[ReservationId, ...]:
    """Devolver IDs de reservas ocupantes solapadas en orden determinista.

    Rechaza datos de otro ámbito o recurso, incluidos los no ocupantes, para
    que una consulta defectuosa no se considere una comprobación segura. La
    conversión de TimeRange a intervalo semiabierto exige duración positiva.
    Esta función es una evaluación sin efectos: NO reserva ni garantiza
    aislamiento frente a cambios concurrentes; la confirmación necesita una
    adjudicación transaccional en el adaptador correspondiente.
    """
    if not (
        isinstance(tenant_id, TenantId)
        and isinstance(business_id, BusinessId)
        and isinstance(location_id, LocationId)
        and isinstance(resource_id, ResourceId)
        and isinstance(interval, ReservationInterval)
    ):
        raise InvariantViolationError("Ámbito o intervalo de consulta inválido")

    conflicts: set[ReservationId] = set()
    for reservation in reservations:
        if not isinstance(reservation, Reservation):
            raise InvariantViolationError("Se esperaba una Reservation")
        if (
            reservation.tenant_id != tenant_id
            or reservation.business_id != business_id
            or reservation.location_id != location_id
            or reservation.resource_id != resource_id
        ):
            raise InvariantViolationError("Reserva fuera del ámbito de la consulta")
        if reservation_occupies_interval(reservation.status):
            existing = ReservationInterval(reservation.time_range.start, reservation.time_range.end)
            if interval.overlaps(existing):
                conflicts.add(reservation.id)
    return tuple(sorted(conflicts, key=str))
