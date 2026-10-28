"""Comandos de reserva."""

from dataclasses import dataclass

from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.messaging.commands import Command
from universal_business.domain.reservations.interval import ReservationInterval
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    ReservationId,
    ResourceId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class ConfirmReservation(Command):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    reservation_id: ReservationId
    idempotency_key: IdempotencyKey


@dataclass(frozen=True, kw_only=True)
class CreateReservation(Command):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    resource_id: ResourceId
    customer_id: CustomerId
    reservation_id: ReservationId
    interval: ReservationInterval
    idempotency_key: IdempotencyKey
    party_size: int | None = None
    notes: str | None = None
