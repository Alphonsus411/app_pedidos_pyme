"""Comandos de pedidos."""

from dataclasses import dataclass

from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.messaging.commands import Command
from universal_business.domain.orders.value_objects import OrderChannel
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    OrderId,
    TenantId,
)


@dataclass(frozen=True, kw_only=True)
class CreateOrder(Command):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    order_id: OrderId
    channel: OrderChannel
    idempotency_key: IdempotencyKey
    customer_id: CustomerId | None = None
