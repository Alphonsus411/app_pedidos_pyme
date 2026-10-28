"""Comandos de reserva."""

from dataclasses import dataclass

from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.messaging.commands import Command
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    LocationId,
    ReservationId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class ConfirmReservation(Command):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    reservation_id: ReservationId
    idempotency_key: IdempotencyKey
