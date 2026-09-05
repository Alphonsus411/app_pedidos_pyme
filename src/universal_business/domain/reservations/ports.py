"""Puertos repositorio para Reservations."""

from __future__ import annotations

from typing import Protocol

from universal_business.domain.reservations.entities import Reservation
from universal_business.domain.reservations.value_objects import ReservationStatus
from universal_business.domain.shared.value_objects.ids import (
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)
from universal_business.domain.shared.value_objects.temporal import TimeRange


class IReservationRepository(Protocol):
    def get(self, reservation_id: ReservationId) -> Reservation | None: ...
    def save(self, reservation: Reservation) -> None: ...

    def list_for_resource_in_range(
        self,
        *,
        tenant_id: TenantId,
        location_id: LocationId,
        resource_id: ResourceId | None = None,
        time_range: TimeRange,
        status: ReservationStatus | None = None,
    ) -> list[Reservation]: ...

    def list_for_customer(
        self,
        *,
        tenant_id: TenantId,
        customer_id: CustomerId,
        status: ReservationStatus | None = None,
    ) -> list[Reservation]: ...


__all__ = ["IReservationRepository"]
