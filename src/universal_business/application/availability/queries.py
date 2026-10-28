"""Solicitud de lectura de disponibilidad de un recurso."""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.application.messaging.queries import Query
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ResourceId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class EvaluateResourceAvailability(Query):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    resource_id: ResourceId
    interval: ReservationInterval
    party_size: int | None = None
