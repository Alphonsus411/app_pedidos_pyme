"""Aggregado mínimo Order (skeleton 0.1). Pricing/line-items viene en FASE 1."""

from __future__ import annotations

from dataclasses import dataclass

from universal_business.domain.orders.value_objects import OrderChannel, OrderStatus
from universal_business.domain.shared.base import BaseEntity
from universal_business.domain.shared.errors import InvariantViolationError
from universal_business.domain.shared.value_objects.ids import (
    BusinessId,
    CustomerId,
    LocationId,
    OrderId,
    TenantId,
)
from universal_business.domain.shared.value_objects.money import Money


@dataclass(kw_only=True)
class Order(BaseEntity[OrderId]):
    """Pedido — genérico (no sectorial)."""

    tenant_id: TenantId
    business_id: BusinessId
    location_id: LocationId  # OBLIGATORIO: pedido asociado a un establecimiento
    status: OrderStatus
    channel: OrderChannel
    total: Money | None = None
    customer_id: CustomerId | None = None
    external_ref: str | None = None
    notes: str | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not isinstance(self.status, OrderStatus):
            raise InvariantViolationError("Order.status debe ser OrderStatus")
        if not isinstance(self.channel, OrderChannel):
            raise InvariantViolationError("Order.channel debe ser OrderChannel")
        if self.total is not None and not isinstance(self.total, Money):
            raise InvariantViolationError("Order.total debe ser Money")
        if self.external_ref is not None:
            er = self.external_ref.strip()
            if not er:
                raise InvariantViolationError("Order.external_ref vacío no permitido")
            object.__setattr__(self, "external_ref", er)


__all__ = ["Order"]
