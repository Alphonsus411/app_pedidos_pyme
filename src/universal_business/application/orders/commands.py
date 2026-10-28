"""Comandos de pedidos."""

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID

from universal_business.application.idempotency import IdempotencyKey
from universal_business.application.messaging.commands import Command
from universal_business.domain.orders.value_objects import OrderChannel
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    OfferingId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


@dataclass(frozen=True, kw_only=True)
class CreateOrder(Command):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    order_id: OrderId
    channel: OrderChannel
    idempotency_key: IdempotencyKey
    customer_id: CustomerId | None = None


@dataclass(frozen=True, kw_only=True)
class AddOrderLine(Command):
    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId
    order_id: OrderId
    offering_id: OfferingId
    line_id: UUID
    quantity: Decimal
    discount: Money
    tax: Money
    idempotency_key: IdempotencyKey
