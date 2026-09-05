"""Aggregado mínimo Reservation (skeleton 0.1). FASE 1 implementa reglas."""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import TimeRange


@dataclass(kw_only=True)
class Reservation(BaseEntity[ReservationId]):
    """Reserva de un Resource en una Location en un TimeRange."""

    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId  # OBLIGATORIO: reserva en una Location concreta
    customer_id: CustomerId
    resource_id: ResourceId
    time_range: TimeRange
    status: ReservationStatus = ReservationStatus.DRAFT
    party_size: int | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.time_range, TimeRange):
            raise InvariantViolationError("Reservation.time_range debe ser TimeRange")
        if not isinstance(self.status, ReservationStatus):
            raise InvariantViolationError("Reservation.status debe ser ReservationStatus")
        if self.party_size is not None and self.party_size < 0:
            raise InvariantViolationError("Reservation.party_size no puede ser negativo")


__all__ = ["Reservation"]
