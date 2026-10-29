"""Consulta de una reserva en un ámbito explícito."""

from dataclasses import dataclass

from universal_business.application.messaging.queries import Query
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class GetReservation(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    reservation_id: ReservationId
