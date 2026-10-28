"""Eventos de ciclo de vida de reservas."""

from dataclasses import dataclass

from universal_business.domain.shared.events import DomainEvent
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class ReservationConfirmed(DomainEvent):
    aggregate_id: ReservationId
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    resource_id: ResourceId
    aggregate_type: str = "Reservation"
